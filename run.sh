#!/bin/bash
source ../venv/bin/activate

addr='10.8.112.221'

if [[ "$1" == 'local' ]]; then
  addr='0.0.0.0'
fi

echo "Connecting to $addr"

fprime-gds --dict ../MomentusTopologyDictionary.json -n --framing-selection csp-plugin --ip-client --ip-address "$addr" --ip-port 8000 --keepalive-interval 0 --no-zmq --tts-port 50054
