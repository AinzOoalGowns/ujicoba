import asyncio
import random
import ssl
import json
import time
import uuid
import os
import gc
from loguru import logger
from websockets_proxy import Proxy, proxy_connect
from fake_useragent import UserAgent
from subprocess import call

# Fungsi untuk memeriksa apakah script dijalankan dari repositori GitHub
def check_git_repository():
    if not os.path.isdir(".git"):
        logger.error("Skrip ini hanya dapat dijalankan jika di-clone dari repositori GitHub.")
        exit()

# Fungsi pembaruan otomatis dari GitHub
def auto_update_script():
    logger.info("Memeriksa pembaruan skrip di GitHub...")
    if os.path.isdir(".git"):
        call(["git", "pull"])
        logger.info("Skrip diperbarui dari GitHub.")
    else:
        logger.error("Repositori ini belum di-clone menggunakan git. Skrip dihentikan.")
        exit()

# Membaca konfigurasi dari file config.json
def load_config():
    if not os.path.exists('config.json'):
        logger.warning("File config.json tidak ditemukan, menggunakan nilai default.")
        return {
            "proxy_retry_limit": 5,
            "reload_interval": 60,
            "max_concurrent_connections": 50
        }
    with open('config.json', 'r') as f:
        return json.load(f)

# Membuat folder data jika belum ada
if not os.path.exists('data'):
    os.makedirs('data')

# Konfigurasi
config = load_config()
proxy_retry_limit = config["proxy_retry_limit"]
reload_interval = config["reload_interval"]
max_concurrent_connections = config["max_concurrent_connections"]

user_agent = UserAgent(os='windows', platforms='pc', browsers='chrome')

# Fungsi untuk memastikan setiap proxy memiliki prefix 'http://'
def normalize_proxy(proxy_list):
    normalized_list = []
    for proxy in proxy_list:
        if not proxy.startswith("http://"):
            normalized_list.append(f"http://{proxy}")
        else:
            normalized_list.append(proxy)
    return normalized_list

# Fungsi untuk memuat ulang daftar proxy
async def reload_proxy_list():
    with open('proxy.txt', 'r') as file:
        proxies = file.read().splitlines()
    proxies = normalize_proxy(proxies)  # Normalisasi proxy
    logger.info("Daftar proxy telah dimuat pertama kali.")
    
    while True:
        await asyncio.sleep(reload_interval)  # Tunggu interval sebelum reload berikutnya
        with open('proxy.txt', 'r') as file:
            proxies = file.read().splitlines()
        proxies = normalize_proxy(proxies)  # Normalisasi proxy
        logger.info("Daftar proxy telah dimuat ulang.")
        return proxies

# Fungsi utama koneksi WebSocket
async def connect_to_wss(socks5_proxy, user_id, semaphore, proxy_failures):
    async with semaphore:
        retries = 0
        backoff = 0.5  # Backoff mulai dari 0.5 detik
        device_id = str(uuid.uuid4())

        while retries < proxy_retry_limit:
            try:
                custom_headers = {
                    "User-Agent": user_agent.random,
                    "Accept-Language": random.choice(["en-US", "en-GB", "id-ID"]),
                    "Referer": random.choice(["https://www.google.com/", "https://www.bing.com/"]),
                    "X-Forwarded-For": ".".join(map(str, (random.randint(1, 255) for _ in range(4)))),
                    "DNT": "1",
                    "Connection": "keep-alive"
                }

                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                uri = random.choice(["wss://proxy.wynd.network:4444/", "wss://proxy.wynd.network:4650/"])
                proxy = Proxy.from_url(socks5_proxy)

                async with proxy_connect(uri, proxy=proxy, ssl=ssl_context, server_hostname="proxy.wynd.network",
                                         extra_headers=custom_headers) as websocket:

                    async def send_ping():
                        while True:
                            ping_message = json.dumps({
                                "id": str(uuid.uuid4()), "version": "1.0.0", "action": "PING", "data": {}
                            })
                            await websocket.send(ping_message)
                            await asyncio.sleep(random.uniform(1, 3))

                    asyncio.create_task(send_ping())

                    while True:
                        try:
                            response = await asyncio.wait_for(websocket.recv(), timeout=5)
                            message = json.loads(response)

                            if message.get("action") == "AUTH":
                                auth_response = {
                                    "id": message["id"],
                                    "origin_action": "AUTH",
                                    "result": {
                                        "browser_id": device_id,
                                        "user_id": user_id,
                                        "user_agent": custom_headers['User-Agent'],
                                        "timestamp": int(time.time()),
                                        "device_type": "desktop",
                                        "version": "4.28.1",
                                    }
                                }
                                await websocket.send(json.dumps(auth_response))

                            elif message.get("action") == "PONG":
                                logger.success("BERHASIL")
                                await websocket.send(json.dumps({"id": message["id"], "origin_action": "PONG"}))

                        except asyncio.TimeoutError:
                            logger.warning("Koneksi ulang.")
                            break

            except Exception as e:
                retries += 1
                logger.error(f"ERROR: {e}")
                await asyncio.sleep(min(backoff, 2))  # Exponential backoff
                backoff *= 1.2

        if retries >= proxy_retry_limit:
            proxy_failures.append(socks5_proxy)
            logger.info(f"Proxy {socks5_proxy} telah dihapus.")

# Fungsi utama
async def main():
    # Periksa apakah dijalankan dari repositori GitHub
    check_git_repository()

    # Cek pembaruan skrip dari GitHub
    auto_update_script()

    # Membaca user ID dari file
    if os.path.exists("userid.txt"):
        with open("userid.txt", "r") as f:
            user_id = f.read().strip()
    else:
        logger.error("File userid.txt tidak ditemukan. Program dihentikan.")
        exit()

    # Load proxy pertama kali tanpa delay
    with open('proxy.txt', 'r') as file:
        proxies = file.read().splitlines()
    proxies = normalize_proxy(proxies)  # Normalisasi proxy
    logger.info("Daftar proxy pertama kali dimuat.")
    
    # Task queue untuk membagi beban
    queue = asyncio.Queue()
    for proxy in proxies:
        await queue.put(proxy)
    
    # Memulai task reload proxy secara berkala
    proxy_list_task = asyncio.create_task(reload_proxy_list())

    semaphore = asyncio.Semaphore(max_concurrent_connections)  # Batasi koneksi bersamaan
    proxy_failures = []

    tasks = []
    for _ in range(len(proxies)):
        task = asyncio.create_task(process_proxy(queue, user_id, semaphore, proxy_failures))
        tasks.append(task)

    await asyncio.gather(*tasks)

async def process_proxy(queue, user_id, semaphore, proxy_failures):
    while not queue.empty():
        socks5_proxy = await queue.get()
        await connect_to_wss(socks5_proxy, user_id, semaphore, proxy_failures)

if __name__ == "__main__":
    asyncio.run(main())
