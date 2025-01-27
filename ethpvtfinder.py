# ethpvtfinder/ethpvtfinder.py (Version 1.0)
import requests
from bs4 import BeautifulSoup
import re
import time
import argparse
import os
import signal
import yaml
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from eth_utils import keccak

# ANSI escape codes for colors
BRIGHT_GREEN = "\033[92m"
BRIGHT_RED = "\033[91m"
RESET_COLOR = "\033[0m"

# --- Configuration (loaded from config.yaml) ---
# Make sure to handle the case where config.yaml is in the package directory
try:
    # When running normally
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    # When imported as a package
    try:
        import pkg_resources
        config_path = pkg_resources.resource_filename('ethpvtfinder', 'config.yaml')
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except (ImportError, FileNotFoundError):
        print(f"{BRIGHT_RED}Error: config.yaml not found. "
              f"Please ensure it's in the package directory or the script's root.{RESET_COLOR}")
        exit(1)

ETHERSCAN_BASE_URL = config["etherscan_base_url"]
ETHPLORER_API_KEY = os.environ.get("ETHPLORER_API_KEY", "freekey")  # Default to "freekey"
POSSIBLES_FILE = config["possibles_file"]
FINAL_FILE = config["final_file"]
LAST_PROCESSED_PAGE_FILE = config["last_processed_page_file"]
DEBUG_FILE = config["very_verbose_file"]
DELAY_BETWEEN_REQUESTS = config["delay_between_requests"]
MAX_RETRIES = config["max_retries"]

# --- Headers (including User-Agent) ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

class TokenBucket:
    def __init__(self, tokens, fill_rate):
        self.capacity = float(tokens)
        self._tokens = float(tokens)
        self.fill_rate = float(fill_rate)
        self.timestamp = time.time()

    def consume(self, tokens):
        if tokens <= self.tokens:
            self._tokens -= tokens
            return True
        return False

    @property
    def tokens(self):
        if self._tokens < self.capacity:
            now = time.time()
            delta = self.fill_rate * (now - self.timestamp)
            self._tokens = min(self.capacity, self._tokens + delta)
            self.timestamp = now
        return self._tokens

# --- Rate Limiter (using TokenBucket) ---
rate_limiter = TokenBucket(2, 1)  # 2 requests per second (adjust if needed)

def is_valid_private_key(key_string):
    return bool(re.fullmatch(r"^[0-9a-fA-F]{64}$", key_string))

def private_key_to_address(private_key_hex, verbose, debug_file):
    """
    Converts a private key (hexadecimal string) to an Ethereum address.
    """
    try:
        if verbose:
            print(f"{BRIGHT_GREEN}  Private Key (hex): {private_key_hex}{RESET_COLOR}")

        private_key = int(private_key_hex, 16)
        curve = ec.SECP256K1()
        signing_key = ec.derive_private_key(private_key, curve, default_backend())
        public_key = signing_key.public_key()
        public_key_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        public_key_bytes = public_key_bytes[1:]
        address = keccak(public_key_bytes)[-20:]
        derived_address = '0x' + address.hex()

        if verbose:
            print(f"{BRIGHT_GREEN}  Derived Address: {derived_address}{RESET_COLOR}")
        if debug_file:
            debug_file.write(f"Derived Address: {derived_address}\n")

        return derived_address

    except Exception as e:
        if debug_file:
            debug_file.write(f"Error deriving address: {e}\n")
        print(f"{BRIGHT_RED}  Error deriving address: {e}{RESET_COLOR}")
        return None

def get_address_info(address, verbose, debug_file):
    """
    Gets ETH and token balances for an address using the Ethplorer API.
    """
    try:
        url = f"https://api.ethplorer.io/getAddressInfo/{address}"
        params = {"apiKey": ETHPLORER_API_KEY}

        if verbose:
            print(f"{BRIGHT_GREEN}  Getting address info for: {address}{RESET_COLOR}")
        if debug_file:
            debug_file.write(f"GET request to: {url} with params: {params}\n")

        if rate_limiter.consume(1):
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if debug_file:
                debug_file.write(f"Response: {response.status_code} {response.text}\n")

            return data

        else:
            print(f"{BRIGHT_RED}  Rate limit exceeded, waiting...{RESET_COLOR}")
            time.sleep(1)
            return get_address_info(address, verbose, debug_file)

    except requests.exceptions.RequestException as e:
        if debug_file:
            debug_file.write(f"Error fetching address info from Ethplorer: {e}\n")
        print(f"{BRIGHT_RED}  Error fetching address info from Ethplorer: {e}{RESET_COLOR}")
        return None
    except Exception as e:
        if debug_file:
            debug_file.write(f"An unexpected error occurred (Ethplorer API): {e}\n")
        if verbose:
            print(f"{BRIGHT_RED}  An unexpected error occurred (Ethplorer API): {e}{RESET_COLOR}")
        return None

def get_messages_from_page(url, verbose, debug_file, retries=0):
    messages = []
    try:
        if verbose:
            print(f"  Fetching page: {url}")
        if debug_file:
            debug_file.write(f"Fetching page: {url}\n")

        if rate_limiter.consume(1):
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()

            if debug_file:
                debug_file.write(f"Response: {response.status_code}\n")
                debug_file.write(f"Response Content:\n{response.text}\n")

            soup = BeautifulSoup(response.content, 'html.parser')
            textarea = soup.find("textarea", {"id": "ContentPlaceHolder1_txtSignedMessageReadonly"})

            if textarea:
                message = textarea.text.strip()
                messages.append(message)
                if verbose:
                    print(f"  Found message: {message}")
                if debug_file:
                    debug_file.write(f"Found message: {message}\n")
            else:
                if verbose:
                    print("  Message textarea not found on page. Skipping to next page.")
                # Check for specific error messages
                if "No records found" in response.text:
                    print("  No more messages found on Etherscan.")
                    return []
                elif "Error! Invalid page number" in response.text:
                    print("  Invalid page number reached.")
                    return []
                else:
                    return messages

            return messages
        else:
            print(f"{BRIGHT_RED}  Rate limit exceeded, waiting...{RESET_COLOR}")
            time.sleep(1)
            return get_messages_from_page(url, verbose, debug_file, retries)

    except requests.exceptions.RequestException as e:
        if retries < MAX_RETRIES:
            if debug_file:
                debug_file.write(f"Error fetching page {url}: {e}\n")
            print(f"{BRIGHT_RED}  Error fetching page {url}: {e}{RESET_COLOR}")
            print(f"{BRIGHT_RED}  Retrying... ({retries + 1}/{MAX_RETRIES}){RESET_COLOR}")
            time.sleep(2 ** retries)
            return get_messages_from_page(url, verbose, debug_file, retries + 1)
        else:
            if debug_file:
                debug_file.write(f"Max retries reached. Could not fetch page: {url}\n")
            print(f"{BRIGHT_RED}  Max retries reached. Could not fetch page: {url}{RESET_COLOR}")
            return []
    except Exception as e:
        if debug_file:
            debug_file.write(f"Error parsing page {url}: {e}\n")
        if verbose:
            print(f"{BRIGHT_RED}  Error parsing page {url}: {e}{RESET_COLOR}")
        return []

def signal_handler(sig, frame):
    print(f"{BRIGHT_RED}\nCtrl+C detected. Saving data and exiting gracefully...{RESET_COLOR}")
    if debug_file:
        debug_file.write(f"Ctrl+C detected. Exiting.\n")
        debug_file.close()
    possibles_file.close()
    final_file.close()
    exit(0)

def main():
    parser = argparse.ArgumentParser(description="Scrape Etherscan for potential private keys.")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode and write output to debug.txt")
    parser.add_argument("-s", "--start_page", type=int, default=1, help="Page number to start scraping from.")
    args = parser.parse_args()

    debug = args.debug
    verbose = True
    start_page = args.start_page

    global debug_file
    if debug:
        debug_file = open(DEBUG_FILE, "a")
        print("Debug mode enabled. Debug output will be written to debug.txt")
    else:
        debug_file = None

    # --- File Handling ---
    global possibles_file
    global final_file
    possibles_file = open(POSSIBLES_FILE, "a")
    final_file = open(FINAL_FILE, "a")

    # --- Signal Handler for Ctrl+C ---
    signal.signal(signal.SIGINT, signal_handler)

    page_num = start_page

    while True:
        page_url = f"{ETHERSCAN_BASE_URL}/{page_num}"
        print(f"Processing page: {page_url}")

        messages = get_messages_from_page(page_url, verbose, debug_file)

        if not messages:
            print("No more messages found or an error occurred. Exiting.")
            if debug_file:
                debug_file.write("No more messages found or an error occurred. Exiting.\n")
                debug_file.close()
            break

        for message in messages:
            potential_keys = re.findall(r"[0-9a-fA-F]{64}", message)
            for key_string in potential_keys:
                if is_valid_private_key(key_string):
                    print(f"  Potential private key found: {key_string}")
                    if debug_file:
                        debug_file.write(f"Potential private key found: {key_string}\n")

                    # Write to possibles.txt immediately
                    possibles_file.write(f"Page: {page_num}\nMessage: {message}\nPotential Key: {key_string}\n\n")
                    possibles_file.flush()

                    # Derive address
                    address = private_key_to_address(key_string, verbose, debug_file)

                    if address:
                        print(f"{BRIGHT_GREEN}  Derived address: {address}{RESET_COLOR}")

                        # Get address info from Ethplorer
                        address_info = get_address_info(address, verbose, debug_file)

                        if address_info:
                            # --- Print and write ETH balance ---
                            eth_balance = float(address_info.get("ETH", {}).get("balance", 0))
                            eth_price_info = address_info.get("ETH", {}).get("price", {})
                            eth_price = float(eth_price_info.get("rate", 0)) if eth_price_info else 0.0
                            eth_value = eth_balance * eth_price

                            print(f"{BRIGHT_GREEN}  Address: {address}, ETH Balance: {eth_balance}, Price: ${eth_price:.2f}, USD Value: ${eth_value:.2f}{RESET_COLOR}")
                            final_file.write(f"Page: {page_num}\nPrivate Key: {key_string}\nAddress: {address}, ETH Balance: {eth_balance}, Price: ${eth_price:.2f}, USD Value: ${eth_value:.2f}\n")

                            # --- Print and write all token balances ---
                            if "tokens" in address_info:
                                for token in address_info["tokens"]:
                                    token_info = token.get("tokenInfo", {})
                                    token_name = token_info.get("name", "N/A")
                                    token_balance = float(token.get("balance", 0)) / (10 ** float(token_info.get("decimals", 0)))
                                    token_price_info = token_info.get("price", {})
                                    token_price = float(token_price_info.get("rate", 0)) if token_price_info else 0.0
                                    token_value = token_balance * token_price

                                    print(f"{BRIGHT_GREEN}  Address: {address}, Token: {token_name}, Balance: {token_balance}, Price: ${token_price:.2f}, USD Value: ${token_value:.2f}{RESET_COLOR}")
                                    final_file.write(f"Address: {address}, Token: {token_name}, Balance: {token_balance}, Price: ${token_price:.2f}, USD Value: ${token_value:.2f}\n")

                            final_file.flush() # Flush after writing all info

                        else:
                            print(f"{BRIGHT_RED}  Could not retrieve address info for: {address}{RESET_COLOR}")
                            if debug_file:
                                debug_file.write(f"Could not retrieve address info for: {address}\n")
                    else:
                        print(f"{BRIGHT_RED}  Could not derive address for key: {key_string}{RESET_COLOR}")
                        if debug_file:
                            debug_file.write(f"Could not derive address for key: {key_string}\n")

        page_num += 1

        # Save the last processed page number
        with open(LAST_PROCESSED_PAGE_FILE, "w") as f:
            f.write(str(page_num))

        print(f"{BRIGHT_GREEN}...Next page...{RESET_COLOR}")
        time.sleep(DELAY_BETWEEN_REQUESTS)

    # Close files when exiting the loop
    if debug_file:
            debug_file.close()
        possibles_file.close()
        final_file.close()
        print("Script finished.")

    if __name__ == "__main__":
        main()
