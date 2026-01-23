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

# Defaults
addr='10.8.112.221'
CONFIG_FILE="${CONFIG_FILE:-}"   # env override

usage() {
    echo "Usage: $0 [local] [--config <configfile>]"
    echo
    echo "Options:"
    echo "  local                  Connect to 0.0.0.0"
    echo "  --config <configfile>  YAML config file (exported as CONFIG_FILE)"
    exit 1
}

# Argument parsing
while [[ $# -gt 0 ]]; do
    case "$1" in
        local)
            addr='0.0.0.0'
            shift
            ;;
        --config)
            [[ -z "$2" ]] && usage
            CONFIG_FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            ;;
    esac
done

# Export so Python can read it
export CONFIG_FILE

echo -e "${GREEN}Connecting to $addr${NC}"
[[ -n "$CONFIG_FILE" ]] && echo -e "${GREEN}Using config: $CONFIG_FILE${NC}"
echo

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
  --tts-port 50055
