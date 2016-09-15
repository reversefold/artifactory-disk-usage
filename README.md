# Artifactory Disk Usage

Gives you a visualization of the sizes of the files in your [artifactory](https://www.jfrog.com/artifactory/) repositories recursively through the directories. Similar to [FileLight](http://methylblue.com/filelight/) or [DaisyDisk](https://daisydiskapp.com/).

## `get_directory_sizes.py`

First you need to run `get_directory_sizes.py` to index the files on your artifactory. You'll need to install the requirements listed in `requirements.txt` for the script to work:
```shell
pip install -r requirements.txt
```

Then to run the script you need to specify the base URL to your artifactory instance and the names of the repositories you want to index:
```shell
./get_directory_sizes.py http://artifactory.example.org:8000/artifactory my-repo my-repo-2
```

This will output 3 json files with the sizes of all of the directories in `my-repo` and `my-repo-2`.
`directory_sizes_flat.json`: a flat file which lists every directory and its size. One is a tree file with more information.
`directory_sizes_tree.json`: a tree structure with the child folders in a dictionary for easy access
`directory_sizes_d3tree.json`: a tree structure witht he child folders in an array for use with `directory_sizes.html`

## `directory_sizes.html`
Once you have `directory_sizes_d3tree.json` you can use this html file to visualize the data as an interactive sunburst graph. To view you will need to put the json file and html file on a web server. The easiest way is to run the following command:
```shell
python -m SimpleHTTPServer
```

You can then view the html file at [http://localhost:8000/directory_sizes.html](http://localhost:8000/directory_sizes.html).
