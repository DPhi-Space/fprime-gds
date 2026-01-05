#!/bin/bash

# Bash colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "\n${YELLOW}############################################################${NC}"
echo -e "${YELLOW}WARNING:${NC} Please modify the .env file in the parent 'testbench/' folder"
echo -e "${YELLOW}        ${NC} to set which system (EM, QM, FM) you want to interface with.${NC}"
echo -e "${YELLOW}############################################################\n${NC}"

# Activate virtual environment
if [ -f "../venv/bin/activate" ]; then
    source ../venv/bin/activate
else
    echo -e "${RED}Error: Virtual environment not found at ../venv${NC}"
    exit 1
fi

# Default IP
addr='10.8.112.221'

# Usage function
usage() {
    echo "Usage: $0 [local]"
    echo "  local          Optional argument to connect to local address (0.0.0.0)"
    exit 1
}

# Optional argument for local IP
if [[ "$1" == "local" ]]; then
    addr='0.0.0.0'
elif [[ -n "$1" ]]; then
    echo "Unknown argument: $1"
    usage
fi

echo -e "${GREEN}Connecting to $addr${NC}\n"

# Run fprime-gds
fprime-gds \
  --dict ../MomentusTopologyDictionary.json \
  -n \
  --framing-selection csp-plugin \
  --ip-client \
  --ip-address "$addr" \
  --ip-port 8000 \
  --gui-addr 0.0.0.0 \
  --keepalive-interval 0 \
  --no-zmq \
  --tts-port 50054
