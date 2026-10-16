# Hacker Terminal shell integration for bash (started with --init-file).
# Load the login files the way `bash -l` would, then add hooks that report
# each finished command to the terminal.
if [ -f /etc/profile ]; then
  . /etc/profile
fi
__ht_profile=""
for __ht_file in ~/.bash_profile ~/.bash_login ~/.profile; do
  if [ -f "$__ht_file" ]; then
    __ht_profile="$__ht_file"
    . "$__ht_file"
    break
  fi
done
if [ -z "$__ht_profile" ] && [ -f ~/.bashrc ]; then
  . ~/.bashrc
fi
unset __ht_file __ht_profile

if [ -z "${__HT_INTEGRATION-}" ]; then
  __HT_INTEGRATION=1
  __ht_seq=0 __ht_cmd="" __ht_start="" __ht_status="" __ht_armed=""

  __ht_install() {
    # Startup files may replace PROMPT_COMMAND later (Kali's .bashrc runs
    # PROMPT_COMMAND=echo on the first prompt, overwriting element 0), so
    # check often that our status capture is first and our report is last.
    if (( BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 1) )); then
      local count=${#PROMPT_COMMAND[@]}
      if [[ "${PROMPT_COMMAND[0]-}" == __ht_save_status && "${PROMPT_COMMAND[count-1]-}" == __ht_report ]]; then
        return 0
      fi
      local item
      local -a kept=()
      for item in "${PROMPT_COMMAND[@]}"; do
        [[ $item == __ht_save_status || $item == __ht_report ]] || kept+=("$item")
      done
      PROMPT_COMMAND=(__ht_save_status "${kept[@]}" __ht_report)
    else
      case "$PROMPT_COMMAND" in __ht_save_status\;*\;__ht_report|__ht_save_status\;__ht_report) return 0 ;; esac
      local rest=${PROMPT_COMMAND//__ht_save_status;/}
      rest=${rest//;__ht_report/}
      PROMPT_COMMAND="__ht_save_status;${rest:+$rest;}__ht_report"
    fi
  }

  __ht_preexec() {
    __ht_install
    # The DEBUG trap fires for every simple command; only the first one
    # after a prompt is the user's command line.
    [ -n "$__ht_armed" ] || return 0
    case "$BASH_COMMAND" in __ht_*) return 0 ;; esac
    __ht_armed=""
    __ht_start=${EPOCHREALTIME/[.,]/}
    __ht_cmd=$(HISTTIMEFORMAT= builtin history 1)
    __ht_cmd=${__ht_cmd#*[0-9]  }
  }

  __ht_save_status() {
    __ht_status=$?
    __ht_armed=""  # the rest of PROMPT_COMMAND is not the user's command
  }

  __ht_report() {
    local duration=0 command="$__ht_cmd" expanded lines
    if [ -n "$__ht_start" ]; then
      duration=$(( (${EPOCHREALTIME/[.,]/} - __ht_start) / 1000 ))
    else
      __ht_status=""
    fi
    expanded=${PS1@P}
    lines=${expanded//[^$'\n']/}
    command=${command:0:300}  # the terminal drops over-long values
    command=${command//%/%25}
    command=${command//\\/%5C}
    command=${command//;/%3B}
    command=${command//|/%7C}
    command=${command//$'\t'/%09}
    command=${command//$'\n'/%0A}
    command=${command//$'\e'/}
    command=${command//$'\a'/}
    __ht_seq=$(( __ht_seq + 1 ))
    printf '\e]666;vte.ext.hackerterminal.mark=1|%s|%s|%s|%s|%s\e\\' \
      "$__ht_seq" "$__ht_status" "$duration" "$(( ${#lines} + 1 ))" "$command"
    __ht_cmd="" __ht_start=""
    __ht_armed=1
  }

  # Respect a DEBUG trap the user already has (for example bash-preexec).
  if [ -z "$(trap -p DEBUG)" ]; then
    trap '__ht_preexec' DEBUG
  fi
  __ht_install
fi
