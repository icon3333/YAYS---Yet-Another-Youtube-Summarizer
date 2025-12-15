"""
Efficient tail reader for log files.

This module provides utilities to read the last N lines from a file
without loading the entire file into memory. It reads backwards in chunks
to minimize memory usage and I/O operations.
"""

import os
from typing import List


def read_tail_lines(
    file_path: str,
    num_lines: int,
    offset: int = 0,
    max_chunk_size: int = 8192
) -> List[str]:
    """
    Efficiently read the last N lines from a file without loading the entire file.

    This function reads the file backwards in chunks, stopping once it has
    collected enough lines. This is much more efficient than reading the
    entire file for large log files.

    Args:
        file_path: Path to the file to read
        num_lines: Maximum number of lines to return
        offset: Number of lines to skip from the end before returning results
                (for pagination). Default is 0.
        max_chunk_size: Size of chunks to read in bytes. Default is 8KB.

    Returns:
        List of lines (with newlines preserved), ordered from oldest to newest.
        Returns empty list if file doesn't exist or is empty.

    Example:
        # Get last 100 lines
        lines = read_tail_lines('/var/log/app.log', 100)

        # Get lines 100-200 from the end (pagination)
        lines = read_tail_lines('/var/log/app.log', 100, offset=100)

    Edge cases handled:
        - Empty file: returns []
        - File smaller than requested lines: returns all lines
        - Offset beyond file: returns []
        - Unicode/special characters: preserves encoding
    """
    # Validate inputs
    if num_lines <= 0:
        return []

    if not os.path.exists(file_path):
        return []

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return []

    # We need to collect (num_lines + offset) lines total,
    # then return only the first num_lines after skipping offset
    total_lines_needed = num_lines + offset

    lines_found = []
    remaining_bytes = b''

    with open(file_path, 'rb') as f:
        # Start from the end of file
        current_pos = file_size

        while current_pos > 0 and len(lines_found) < total_lines_needed:
            # Calculate chunk size (don't read more than what's left)
            chunk_size = min(max_chunk_size, current_pos)
            current_pos -= chunk_size

            # Seek to position and read chunk
            f.seek(current_pos)
            chunk = f.read(chunk_size)

            # Combine with any remaining bytes from previous iteration
            chunk = chunk + remaining_bytes

            # Split into lines (keeping delimiters)
            # We split on \n but need to handle the last partial line
            lines_in_chunk = chunk.split(b'\n')

            # The last element might be incomplete (no trailing \n yet)
            # Save it for next iteration
            if current_pos > 0:
                remaining_bytes = lines_in_chunk[0]
                lines_in_chunk = lines_in_chunk[1:]
            else:
                # We've reached the beginning of file
                remaining_bytes = b''

            # Add newlines back (except for last line if at EOF)
            for i, line in enumerate(reversed(lines_in_chunk)):
                # Decode to string with error handling
                try:
                    line_str = line.decode('utf-8')
                except UnicodeDecodeError:
                    line_str = line.decode('utf-8', errors='replace')

                # Add newline back (all lines except potentially the very last one)
                if not (current_pos == 0 and i == len(lines_in_chunk) - 1 and len(lines_found) == 0):
                    line_str += '\n'

                lines_found.insert(0, line_str)

                if len(lines_found) >= total_lines_needed:
                    break

    # Handle the final remaining bytes (first line of file) if we haven't hit the limit
    if remaining_bytes and len(lines_found) < total_lines_needed:
        try:
            line_str = remaining_bytes.decode('utf-8')
        except UnicodeDecodeError:
            line_str = remaining_bytes.decode('utf-8', errors='replace')
        lines_found.insert(0, line_str)

    # Apply offset and limit
    if offset > 0:
        # Skip 'offset' lines from the end, then take 'num_lines'
        # lines_found is ordered oldest to newest
        # We want to skip the last 'offset' lines
        if offset >= len(lines_found):
            return []
        lines_found = lines_found[:len(lines_found) - offset]

    # Return only the requested number of lines (from the end)
    return lines_found[-num_lines:]


if __name__ == '__main__':
    # Simple test
    import sys
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        num_lines = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        lines = read_tail_lines(file_path, num_lines)
        print(f"Last {num_lines} lines from {file_path}:")
        print("=" * 50)
        for line in lines:
            print(line, end='')
    else:
        print("Usage: python tail_reader.py <file_path> [num_lines]")
