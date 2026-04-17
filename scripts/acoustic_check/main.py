#!/usr/bin/env python3
"""
Real-time audio monitoring and plotting main program
Qt GUI + Matplotlib + UDP receiver + AFSK text decoding
"""

import sys
import asyncio
from graphic import main

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted by user")
    except Exception as e:
        print(f"Program execution error: {e}")
        sys.exit(1)
