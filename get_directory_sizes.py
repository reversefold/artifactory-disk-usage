#!/usr/bin/env python
# Copyright 2016 Justin Patrin
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Usage:
    %(script)s [--verbose] [--num-workers=<n>] [--username=<username>] [--password=<password>] <artifactory-url> <repositories>...

Options:
    <artifactory-url>                     The base URL to access your artifactory (e.g. http://server:port/artifactory)
    <repositories>...                     One or more repositories to get the sizes for
    -u <username> --username=<username>   Artifactory user
    -p <password> --password=<password>   Artifactory password
    -v --verbose                          Verbose output
    -n <n> --num-workers <n>              The number of parallel workers to use to query the artifactory API. [Default: 10]
"""
from __future__ import print_function
import collections
import datetime
import json
import logging
import os
import Queue
import sys
import threading
import time

import docopt
import requests


class Error(Exception):
    pass


def main():
    logging.basicConfig(
        format='%(asctime)s %(levelname)-5.5s [%(thread)d-%(threadName)s] [%(name)s] %(message)s',
        level=logging.INFO
    )
    logging.getLogger('requests').setLevel(logging.WARNING)
    args = docopt.docopt(__doc__ % {'script': os.path.basename(__file__)})
    try:
        get_folder_sizes(
            args['<artifactory-url>'],
            args['<repositories>'],
            args['--username'],
            args['--password'],
            verbose=args['--verbose'],
            num_workers=int(args['--num-workers'])
        )
    except Error:
        sys.exit(1)


def get_folder_sizes(
    artifactory_url, repositories, user=None, password=None,
    verbose=False, num_workers=10
):
    url = '%s/api/application.wadl' % (artifactory_url,)
    auth = (user, password) if user else None
    resp = requests.get(url, auth=auth, timeout=5)
    if resp.status_code != 200:
        if resp.status_code == 401:
            if auth is None:
                logging.error('Artifactory URL appears to require authentication, use --username and --password.')
            else:
                logging.error('Credentials appear to be incorrect.')
        else:
            logging.error('Artifactory URL appears to be incorrect.')
        logging.error('Tried to access %s and got this response: %r\n%s', url, resp, resp.text)
        raise Error('Failed to get application.wadl')
    storage_api_url = '%s/api/storage' % (artifactory_url,)
    initial_folders = ['/%s' % (repo,) for repo in repositories]
    num_queued = len(initial_folders)
    logging.info('Getting recursive folder sizes for repositories: %r', repositories)
    folder_sizes = {'/': 0}
    in_queue = Queue.Queue()
    for folder in initial_folders:
        in_queue.put(('folder', folder))
    out_queue = Queue.Queue()
    stop_event = threading.Event()

    def request_worker():
        session = requests.Session()
        session.auth = auth
        while not stop_event.is_set():
            try:
                (path_type, path) = in_queue.get(timeout=0.1)
                try:
                    if verbose:
                        logging.info('Getting info for %s', path)
                    resp = session.get('%s%s' % (storage_api_url, requests.compat.quote(path)), timeout=30)
                    if resp.status_code == 404:
                        out_queue.put((None, None, None))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    out_queue.put((path_type, path, data))
                except Exception as exc:
                    logging.info('Got exception %r, requeueing', exc)
                    in_queue.put((path_type, path))
                    time.sleep(1)
            except Queue.Empty:
                pass

    request_workers = []
    for _ in xrange(num_workers):
        thr = threading.Thread(target=request_worker)
        thr.start()
        request_workers.append(thr)
    num = 0
    start = datetime.datetime.now()
    try:
        while not in_queue.empty() or not out_queue.empty() or num < num_queued:
            try:
                (path_type, path, data) = out_queue.get(timeout=0.1)
                num += 1
                if not verbose:
                    if num % 20 == 0:
                        sys.stdout.write('.')
                        sys.stdout.flush()
                    if num % 1000 == 0:
                        sys.stdout.write(' %u %s\n' % (num, datetime.datetime.now() - start))
                if data is None:
                    continue
                if path_type == 'file':
                    size = data['size']
                    if str(int(size)) != str(size):
                        raise Exception(size)
                    size = int(size)
                    folders = os.path.dirname(path).split('/')
                    while folders:
                        path = '/'.join(folders)
                        if not path:
                            path = '/'
                        logging.debug('%s += %u', path, size)
                        folder_sizes.setdefault(path, 0)
                        folder_sizes[path] += size
                        folders.pop()
                else:
                    folder_sizes.setdefault(path, 0)
                    if 'children' not in data:
                        continue
                    for child in data['children']:
                        if data['path'] == '/':
                            data['path'] = ''
                        child_uri = '%s%s%s' % ('/'.join(path.split('/')[:2]), data['path'], child['uri'])
                        num_queued += 1
                        in_queue.put((('folder' if child['folder'] else 'file'), child_uri))
            except Queue.Empty:
                pass
    finally:
        if verbose:
            logging.info('Stopping workers')
        stop_event.set()
        for thr in request_workers:
            thr.join()

    logging.info(' %u %s' % (num, datetime.datetime.now() - start))
    items = sorted(folder_sizes.items(), key=lambda i: i[0])
    logging.info('Writing directory_sizes_flat.json')
    with open('directory_sizes_flat.json', 'w') as f:
        f.write(json.dumps(items, indent=4))

    tree = {}
    for path, s in items:
        dirs = path.split('/')
        if path == '/':
            tree['/'] = {'path': path, 'size': s, 'children': collections.OrderedDict()}
            continue
        cd = tree['/']
        for d in dirs[1:-1]:
            cd = cd['children'][d]
        cd['children'][dirs[-1]] = {'path': path, 'size': s, 'children': collections.OrderedDict()}
    logging.info('Writing directory_sizes_tree.json')
    with open('directory_sizes_tree.json', 'w') as f:
        f.write(json.dumps(tree, indent=4))

    d3tree = {"name": "/", "size": -1, "path": "/", "children": []}
    for path, s in items:
        dirs = path.split('/')
        if path == '/':
            d3tree = {'name': path, 'path': path, 'size': s, 'children': []}
            continue
        cd = d3tree
        for d in dirs[1:-1]:
            cd = [c for c in cd['children'] if c['name'] == d][0]
        cd['children'].append({'name': dirs[-1], 'path': path, 'size': s, 'children': []})
    logging.info('Writing directory_sizes_d3tree.json')
    with open('directory_sizes_d3tree.json', 'w') as f:
        f.write(json.dumps(d3tree, indent=4))


if __name__ == '__main__':
    main()
