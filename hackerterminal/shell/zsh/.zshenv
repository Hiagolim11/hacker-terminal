# Hacker Terminal shell integration for zsh, loaded through a temporary ZDOTDIR.
# It restores your ZDOTDIR first, so your own .zshenv/.zprofile/.zshrc load
# exactly as usual; it only adds hooks that report each finished command.
if [[ -n "${HACKER_TERMINAL_ZDOTDIR-}" ]]; then
  ZDOTDIR="$HACKER_TERMINAL_ZDOTDIR"
else
  unset ZDOTDIR
fi
unset HACKER_TERMINAL_ZDOTDIR
if [[ -f "${ZDOTDIR:-$HOME}/.zshenv" ]]; then
  source "${ZDOTDIR:-$HOME}/.zshenv"
fi

if [[ -o interactive && -z "${__HT_INTEGRATION-}" ]]; then
  typeset -g __HT_INTEGRATION=1 __ht_seq=0 __ht_cmd="" __ht_start="" __ht_status=""
  zmodload zsh/datetime 2>/dev/null
  autoload -Uz add-zsh-hook add-zle-hook-widget

  __ht_urlencode() {
    # Byte by byte, so accents and spaces become a valid file:// URI.
    emulate -L zsh
    setopt no_multibyte
    local text=$1 out= char
    for char in ${(s::)text}; do
      if [[ $char == [A-Za-z0-9/._~-] ]]; then
        out+=$char
      else
        printf -v char '%%%02X' "'$char"
        out+=$char
      fi
    done
    REPLY=$out
  }

  __ht_preexec() {
    __ht_cmd="$1"
    __ht_start="$EPOCHREALTIME"
  }

  __ht_precmd() {
    __ht_status=$?
    if [[ -z "${__ht_hooked-}" ]]; then
      # Registered on the first prompt, after every startup file ran: system
      # zshrc files define zle-line-init themselves, which would replace a
      # hook installed earlier. add-zle-hook-widget keeps and chains theirs.
      typeset -g __ht_hooked=1
      add-zle-hook-widget line-init __ht_report
      # Flatpak: ht-open lives outside the sandbox; appended after the login
      # files, which may reset PATH.
      if [[ -n "${HACKER_TERMINAL_TOOLS-}" && ":$PATH:" != *":$HACKER_TERMINAL_TOOLS:"* ]]; then
        PATH="$PATH:$HACKER_TERMINAL_TOOLS"
      fi
    fi
    # Current directory (OSC 7), also where the distro's vte.sh is missing.
    __ht_urlencode "$PWD"
    printf '\e]7;file://%s%s\e\\' "${HOST-}" "$REPLY"
  }

  __ht_report() {
    # Runs when the line editor starts: the prompt is fully drawn, so the
    # terminal sees this mark exactly on the prompt line.
    local duration=0 command="$__ht_cmd" lines
    if [[ -n "$__ht_start" ]]; then
      duration=$(( (EPOCHREALTIME - __ht_start) * 1000 ))
      duration=${duration%.*}
    else
      __ht_status=""
    fi
    lines=${(%)PROMPT}
    lines=${#lines//[^$'\n']/}
    command=${command[1,300]}  # the terminal drops over-long values
    command=${command//\%/%25}
    command=${command//\\/%5C}
    command=${command//;/%3B}
    command=${command//|/%7C}
    command=${command//$'\t'/%09}
    command=${command//$'\n'/%0A}
    command=${command//$'\e'/}
    command=${command//$'\a'/}
    (( __ht_seq++ ))
    printf '\e]666;vte.ext.hackerterminal.mark=1|%s|%s|%s|%s|%s\e\\' \
      "$__ht_seq" "$__ht_status" "$duration" "$(( lines + 1 ))" "$command"
    __ht_cmd="" __ht_start=""
  }

  add-zsh-hook preexec __ht_preexec
  add-zsh-hook precmd __ht_precmd
fi
