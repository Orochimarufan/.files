#!/bin/sh
find "$HOME/.steam/root/" \( -name libgcc_s.so* -o -name libstdc++.so* -o -name libxcb.so* \) -print -delete
