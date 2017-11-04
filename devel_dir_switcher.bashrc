#!/bin/bash
# devel_dir_switcher parameter-completion

_devel_dir_switcher_completion()   #  By convention, the function name
{                 #+ starts with an underscore.
    local cur prev cmd
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd="${COMP_WORDS[0]}"

    # TODO: BASH conditionals ...
    if [[ "$COMP_CWORD" -gt 1 ]]; then
        if [[ "$cmd" = "cs" ]]; then
            # cs and cb only require one arg
            COMPREPLY=()
            return 0
        elif [[ "$cmd" = "cb" ]]; then
            # cs and cb only require one arg
            COMPREPLY=()
            return 0
        elif [[ "$COMP_CWORD" -gt 2 ]]; then
            # definitively no more args now even when using devel_dir_switcher.py
            COMPREPLY=()
            return 0
        fi
    fi
  case "$prev" in
    cs|source|cb|build)
      local possibilities
      possibilities=$(devel_dir_switcher.py cache-lookup "$cur")
      # local possibilities="source dirs asd f g"
      COMPREPLY=( $( compgen -W "$possibilities" -- "$cur" ) )
    ;;
    update-cache)
      # COMPREPLY=( $( compgen -W '2 3 4 5 6 7 8 9 10 <depth>' -- $cur ) )
      return 1
    ;;
    *)
      COMPREPLY=( $( compgen -W 'source build update-cache check-cache cleanup-cache' -- "$cur" ) )
    ;;
  esac

  return 0
}

complete -F _devel_dir_switcher_completion -o dirnames devel_dir_switcher.py cs cb
#        ^^ ^^^^^^^^^^^^  Invokes the function devel_dir_switcher_completion

function cs() {
        local SRCDIR
        SRCDIR=$(devel_dir_switcher.py source "$@")
        if [[ $? -gt 0 ]]; then
                return 1
        else
                cd  "$SRCDIR" || return 1
        fi
}

function cb() {
        local BUILDDIR
        BUILDDIR=$(devel_dir_switcher.py build "$@")
        if [[ $? -gt 0 ]]; then
                return 1
        else
                cd  "$BUILDDIR" || return 1
        fi
}
