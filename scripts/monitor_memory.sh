#!/bin/bash
SWAP_USED=$(free | grep Swap | awk '{print $3}')
SWAP_TOTAL=$(free | grep Swap | awk '{print $2}')

if [ $SWAP_TOTAL -eq 0 ]; then exit 0; fi

SWAP_PCT=$((SWAP_USED * 100 / SWAP_TOTAL))

if [ $SWAP_PCT -gt 80 ]; then
    echo "$(date): Swap at ${SWAP_PCT}% — clearing" >> /opt/complynex/logs/memory.log
    swapoff -a && swapon -a
    echo "$(date): Swap cleared" >> /opt/complynex/logs/memory.log
fi
