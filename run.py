import sys
import asyncio  # Pastikan asyncio diimpor
sys.path.append('build/lib.linux-aarch64-cpython-312')  # Menambahkan folder ke path
import script1  # Mengimpor modul yang telah dikompilasi

# Menjalankan fungsi main yang merupakan coroutine
asyncio.run(script1.main())  # Gunakan asyncio.run untuk menjalankan coroutine