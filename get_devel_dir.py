#!/usr/bin/env python3

import json
import sys
import os
import subprocess

builddir = "/build/"
sourcedirs = ["/home/alex/devel/", "/staticdata/sources/"]


def updateCache(path, depth, cacheData, cacheFilePath):
    dirs = subprocess.check_output(['find', path, '-maxdepth', str(depth), '-type', 'd',
                                    '-name', '.git', '-printf', '%h\\0'])
    dirsList = dirs.decode('utf-8').split('\0')
    print(dirsList)
    for d in dirsList:
        if not d:
            continue
        d = os.path.realpath(d)
        repoName = os.path.basename(d)
        if repoName not in cacheData:
            cacheData[repoName] = [d]
        elif d not in cacheData[repoName]:
            cacheData[repoName].append(d)
        else:
            print('Repo', d, 'already exists in cache', file=sys.stderr)
    # print(json.dumps(cacheData), file=sys.stderr)
    with open(cacheFilePath, 'w+') as cacheFile:
        json.dump(cacheData, cacheFile, indent=4)
        cacheFile.flush()


def findInCache(path, cacheData):
    if not path or '/' in path or path not in cacheData:
        return None
    dirs = cacheData[path]
    if len(dirs) == 1:
        return dirs[0]
    print("Multiple source directories found for name", path, file=sys.stderr)
    for i, s in enumerate(dirs):
        print('  [' + str(i) + ']', s, file=sys.stderr)
    try:
        # input prompts on stdout, but we read stdout -> print to stderr instead
        print('Which one did you mean? ', file=sys.stderr, end='')
        chosen = input()
        return dirs[int(chosen)]
    except:
        sys.exit('Invalid choice:' + chosen)


def output_result(r):
    print(r)
    sys.exit()


if "--help" in sys.argv:
    print("Usage: get_devel_dir.py source|build [dir]")
    sys.exit()

if len(sys.argv) < 2:
    sys.exit("Need at least one argument!")

type = sys.argv[1]
path = sys.argv[2] if len(sys.argv) >= 3 else None
cwd = os.path.realpath(os.getcwd()) + '/'

cacheDir = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
cacheFilePath = os.path.join(cacheDir, "devel-dirs.cache")
cacheData = {}
try:
    # try:
    with open(cacheFilePath, 'r') as cacheFile:
        cacheData = json.load(cacheFile)
except:
    print('Cache data was invalid, assuming empty!', file=sys.stderr)

if type == "build":
    cachedSourceDir = findInCache(path, cacheData)
    if cachedSourceDir:
        path = cachedSourceDir
    else:
        path = cwd
    if path.startswith(builddir) or path == builddir:
        sys.stderr.write("Already in build dir.\n")
        output_result(path)
    for sourcedir in sourcedirs:
        if path.startswith(sourcedir):
            output_result(path.replace(sourcedir, builddir))
    # not in source dir before -> change to build dir root
    output_result(builddir)
elif type == "source":
    cachedSourceDir = findInCache(path, cacheData)
    if cachedSourceDir:
        output_result(cachedSourceDir)
    path = cwd
    if path.startswith(builddir):
        output_result(path.replace(builddir, sourcedirs[0]))
    for sourcedir in sourcedirs:
        if path.startswith(sourcedir) or path == sourcedir:
            sys.stderr.write("Already in source dir.\n")
            output_result(path)
    # not in build dir before -> change to source dir root
    output_result(sourcedirs[0])
elif type == "update-cache":
    depth = sys.argv[3] if len(sys.argv) >= 4 else 2

    print('saving to', cacheFilePath, file=sys.stderr)
    updateCache(path, depth, cacheData, cacheFilePath)
else:
    sys.exit("Type must be be eiter 'build' or 'source'")
