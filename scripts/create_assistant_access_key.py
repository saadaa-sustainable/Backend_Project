"""Generate one user access key locally; no database or network access.

Run: python scripts/create_assistant_access_key.py --name 'Team member'
Give the key privately to that person. Merge the printed hash entry into the
server's ASSISTANT_API_ACCESS_KEY_HASHES JSON setting. Do not commit the output.
"""
import argparse
import hashlib
import json
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if not 1 <= len(args.name) <= 100:
        parser.error("Name must be between 1 and 100 characters.")
    key = "sda_" + secrets.token_urlsafe(32)
    print("Private user access key (save securely; do not commit):")
    print(key)
    print("Hash entry for ASSISTANT_API_ACCESS_KEY_HASHES (merge with existing users):")
    print(json.dumps({args.name: hashlib.sha256(key.encode()).hexdigest()}))


if __name__ == "__main__":
    main()
