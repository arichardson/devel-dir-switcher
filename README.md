# devel-dir-switcher: Quickly switch between multiple source and build directories


It will add the following bash commands:

- `cs [project_name]`: change to source dir for `$project_name`. If the project name is omitted it will treat the current working directory as a build directory and will attempt to switch to the corresponding source directory.
- `cb [project_name]`: change to source dir for `$project_name`. If the project name is omitted it will treat the current working directory as a source directory and will attempt to switch to the corresponding build directory.

Both these commands come with bash completion that autocompletes project names.

**Note**: Currently only projects using git are supported as they are found by checking for the existence of `.git`.
If you want to use devel-dir-switcher with non-git project just can create a `.git` file inside the project root directory

## Installation

To install add the directory where you cloned devel-dir-switcher to your `$PATH` and source `devel_dir_switcher.bashrc` from your bashrc:

```bash
$ git clone https://github.com/arichardson/devel-dir-switcher.git
$ echo "export PATH=$PWD/devel-dir-switcher:\$PATH" >> ~/.bashrc
$ echo "source $PWD/devel-dir-switcher/devel-dir-switcher.bashrc" >> ~/.bashrc
```

In order to use devel-dir-switcher you will need to define one or more source roots and (optionally) the corresponding build roots.
This information is saved inside `~/.config/devel_dirs.json`.
If you store most projects inside e.g. `~/devel/` and use out-of-source builds in `~/devel/build` you can create the following `~/.config/devel_dirs.json`:
```json
{
  "directories": [
    { "source": "$HOME/devel/", "build": "$HOME/devel/build/" }
  ]
}
```

Not all projects need build directories so the `build` element can also be `null`:
```json
{
  "directories": [
    { "source": "$HOME/devel/", "build": "$HOME/devel/build/" },
    { "source": "$HOME/other-projects/", "build": null }
  ]
}
```

## More complex source hierarchies (build-dir suffixes and custom overrides)

I often have more than on build directory for one source directory. Such as e.g. one for LLVM debug builds and one for LLVM a release build.
To allow switching to both of them the `directories` json object has a key `build-suffixes` which will be appended to the default directory substition:
Instead of just testing `$SOURCEROOT/project` -> `$BUILDROOT/project` it will also check `$BUILDROOT/project$SUFFIX` and prompt which
one to switch to:

```
alr48@foo:/local/scratch/alr48/cheri/llvm(dev)> cb
Multiple build directories found
  [1] /local/scratch/alr48/cheri/build/llvm-256-build
  [2] /local/scratch/alr48/cheri/build/llvm-debug-build
Which one did you mean? 
```

Invoking `cs` in either of these directories will change back to `/local/scratch/alr48/cheri/llvm`.


# TODO: explain overrides

### Sample config file (~/.config/devel_dirs.json):

```json
{
  "directories": [
    {
      "source": "$HOME/cheri/sources/",
      "build": "$HOME/cheri/build/",
      "build-suffixes": [
        "-build",
        "-256-build",
        "-128-build"
      ]
    },
    {
      "source": "/exports/users/alr48/sources/",
      "build": ["$HOME/cheri/build/", "$HOME/cheri/build-debug/"],
      "build-suffixes": [
        "-build",
        "-256-build",
        "-128-build",
        "-debug-build"
      ]
    }
  ],
  "overrides": [
    {
      "source": "/exports/users/alr48/sources/cheribsd/sys",
      "build": "/home/alr48/cheri/build/cheribsd-obj-256/mips.mips64/exports/users/alr48/sources/cheribsd/sys/CHERI_MALTA64"
    },
    {
      "source": "/exports/users/alr48/sources/cheribsd/",
      "build": ["/home/alr48/cheri/build/cheribsd-obj-256/mips.mips64/exports/users/alr48/sources/cheribsd/", "/home/alr48/cheri/build-debug/cheribsd-obj-256/mips.mips64/exports/users/alr48/sources/cheribsd/"]
    },
    {
      "source": "/exports/users/alr48/sources/cheribsd-lld",
      "build": "/home/alr48/cheri/build/lld-cheribsd-256/mips.mips64/exports/users/alr48/sources/cheribsd-lld"
    },
    {
      "source": "/exports/users/alr48/sources/llvm-postmerge",
      "build": "/home/alr48/cheri/build-postmerge/llvm-256-build"
    },
    {
      "source": "/exports/users/alr48/sources/cheribsd-postmerge",
      "build": "/home/alr48/cheri/build-postmerge/cheribsd-obj-256/mips.mips64/exports/users/alr48/sources/cheribsd-postmerge"
    }
  ]
}

```
