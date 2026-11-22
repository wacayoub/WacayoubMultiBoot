#!/bin/sh
# Test-only remote-control helpers for the receiver (sourced by test commands).
g(){ grab -j 85 -r 1280 /tmp/$1.jpg >/dev/null 2>&1; }
r(){ curl -s -o /dev/null "http://127.0.0.1/api/remotecontrol?command=$1"; sleep ${2:-1.2}; }
w(){ i=0; while [ $i -lt ${2:-90} ]; do tail -2 /tmp/wmultiboot.log | grep -q "$1" && { sleep 1; return 0; }; sleep 1; i=$((i+1)); done; echo "TIMEOUT waiting $1"; }
openwmb(){ echo "UI: --- ${1:-open} ---" >> /tmp/wmultiboot.log; echo ${1:-open} > /tmp/wmb_cmd; w "UI: list" 20; }
