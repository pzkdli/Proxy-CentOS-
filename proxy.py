import random
import string
import subprocess
import datetime
import os
from telethon.sync import TelegramClient
from telethon import events
import sqlite3
import ipaddress

# Thông tin API
API_ID = 28514063
API_HASH = "96f1688ba0ae0f7516af16381c49a5ca"
BOT_TOKEN = "7022711443:AAG2kU-TWDskXqFxCjap1DGw2jjji2HE2Ac"
ADMIN_ID = 7550813603

# Kết nối cơ sở dữ liệu SQLite
def init_db():
    conn = sqlite3.connect('proxies.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS proxies
                 (ipv4 TEXT, port INTEGER, user TEXT, password TEXT, ipv6 TEXT, expiry_date TEXT, is_used INTEGER)''')
    conn.commit()
    conn.close()

# Tạo user ngẫu nhiên (vtoanXXXY)
def generate_user():
    numbers = ''.join(random.choices(string.digits, k=3))
    letter = random.choice(string.ascii_uppercase)
    return f"vtoan{numbers}{letter}"

# Tạo mật khẩu ngẫu nhiên (2 chữ cái in hoa)
def generate_password():
    return ''.join(random.choices(string.ascii_uppercase, k=2))

# Kiểm tra định dạng prefix IPv6
def validate_ipv6_prefix(prefix):
    try:
        ipaddress.IPv6Network(prefix, strict=False)
        return True
    except ValueError:
        return False

# Tạo địa chỉ IPv6 ngẫu nhiên từ prefix
def generate_ipv6_from_prefix(prefix, num_addresses):
    network = ipaddress.IPv6Network(prefix, strict=False)
    base_addr = int(network.network_address)
    max_addr = int(network.broadcast_address)
    ipv6_addresses = []
    
    conn = sqlite3.connect('proxies.db')
    c = conn.cursor()
    c.execute("SELECT ipv6 FROM proxies")
    used_ipv6 = [row[0] for row in c.fetchall()]
    conn.close()
    
    for _ in range(num_addresses):
        while True:
            random_addr = base_addr + random.randint(0, max_addr - base_addr)
            ipv6 = str(ipaddress.IPv6Address(random_addr))
            if ipv6 not in used_ipv6:
                ipv6_addresses.append(ipv6)
                used_ipv6.append(ipv6)
                break
    
    return ipv6_addresses

# Tạo proxy mới với danh sách IPv6
def create_proxy(ipv4, ipv6_addresses, days):
    conn = sqlite3.connect('proxies.db')
    c = conn.cursor()
    
    c.execute("SELECT port FROM proxies")
    used_ports = [row[0] for row in c.fetchall()]
    
    proxies = []
    for ipv6 in ipv6_addresses:
        while True:
            port = random.randint(1000, 60000)
            if port not in used_ports:
                used_ports.append(port)
                break
        
        user = generate_user()
        password = generate_password()
        expiry_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        c.execute("INSERT INTO proxies (ipv4, port, user, password, ipv6, expiry_date, is_used) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (ipv4, port, user, password, ipv6, expiry_date, 0))
        
        with open('/etc/squid/squid.conf', 'a') as f:
            f.write(f"tcp_outgoing_address {ipv6}\n")
            f.write(f"http_port {port}\n")
        
        subprocess.run(['htpasswd', '-b', '/etc/squid/passwd', user, password])
        
        proxies.append(f"{ipv4}:{port}:{user}:{password}")
    
    conn.commit()
    conn.close()
    
    subprocess.run(['systemctl', 'restart', 'squid'])
    
    return proxies

# Kiểm tra kết nối proxy (giả lập)
def check_proxy_usage(ipv4, port):
    return random.choice([True, False])

# Xử lý bot
async def main():
    init_db()
    async with TelegramClient('bot_session', API_ID, API_HASH) as client:
        await client.start(bot_token=BOT_TOKEN)
        
        @client.on(events.NewMessage(from_users=ADMIN_ID, pattern='/start'))
        async def start(event):
            context = getattr(client, '_user_data', {})
            context['state'] = 'prefix'
            client._user_data = context
            await event.reply("Nhập prefix IPv6 (định dạng: 2401:2420:0:102f::/64 hoặc 2401:2420:0:102f:0000:0000:0000:0001/64):")

        @client.on(events.InlineQuery(from_users=ADMIN_ID))
        async def button(event):
            context = getattr(client, '_user_data', {})
            query = event.query.query
            
            if query == 'new':
                if 'prefix' not in context:
                    await event.answer("Vui lòng nhập prefix IPv6 trước bằng lệnh /start!")
                    return
                context['state'] = 'new'
                await event.answer("Nhập số lượng proxy và số ngày (định dạng: số_lượng số_ngày, ví dụ: 5 7):")
            elif query == 'xoa':
                keyboard = [
                    [{"text": "Xóa proxy lẻ", "callback_data": "xoa_le"},
                     {"text": "Xóa hàng loạt", "callback_data": "xoa_all"}]
                ]
                await event.answer("Chọn kiểu xóa:", reply_markup={'inline_keyboard': keyboard})
            elif query == 'check':
                conn = sqlite3.connect('proxies.db')
                c = conn.cursor()
                c.execute("SELECT ipv4, port, user, password, is_used FROM proxies")
                proxies = c.fetchall()
                conn.close()
                
                waiting = [p for p in proxies if p[4] == 0]
                used = [p for p in proxies if p[4] == 1]
                
                with open('waiting.txt', 'w') as f:
                    for p in waiting:
                        f.write(f"{p[0]}:{p[1]}:{p[2]}:{p[3]}\n")
                with open('used.txt', 'w') as f:
                    for p in used:
                        f.write(f"{p[0]}:{p[1]}:{p[2]}:{p[3]}\n")
                
                await event.answer(f"Proxy chờ: {len(waiting)}\nProxy đã sử dụng: {len(used)}\nFile waiting.txt và used.txt đã được tạo.")
            elif query == 'giahan':
                context['state'] = 'giahan'
                await event.answer("Nhập proxy và số ngày gia hạn (định dạng: IP:port:user:pass số_ngày):")
            elif query == 'xoa_le':
                context['state'] = 'xoa_le'
                await event.answer("Nhập proxy cần xóa (định dạng: IP:port:user:pass):")
            elif query == 'xoa_all':
                context['state'] = 'xoa_all'
                await event.answer("Xác nhận xóa tất cả proxy? (Nhập: Xac_nhan_xoa_all)")
            
            client._user_data = context

        @client.on(events.NewMessage(from_users=ADMIN_ID))
        async def message_handler(event):
            context = getattr(client, '_user_data', {})
            text = event.message.text.strip()
            
            if context.get('state') == 'prefix':
                if validate_ipv6_prefix(text):
                    context['prefix'] = text
                    keyboard = [
                        [{"text": "/New", "callback_data": "new"},
                         {"text": "/Xoa", "callback_data": "xoa"}],
                        [{"text": "/Check", "callback_data": "check"},
                         {"text": "/Giahan", "callback_data": "giahan"}]
                    ]
                    await event.reply("Prefix IPv6 đã được lưu. Chọn lệnh:", reply_markup={'inline_keyboard': keyboard})
                    context['state'] = None
                else:
                    await event.reply("Prefix IPv6 không hợp lệ! Vui lòng nhập lại:")
            elif context.get('state') == 'new':
                try:
                    num_proxies, days = map(int, text.split())
                    if num_proxies <= 0 or days <= 0:
                        await event.reply("Số lượng và số ngày phải lớn hơn 0!")
                        return
                    prefix = context.get('prefix')
                    if not prefix:
                        await event.reply("Vui lòng nhập prefix IPv6 trước bằng lệnh /start!")
                        return
                    ipv6_addresses = generate_ipv6_from_prefix(prefix, num_proxies)
                    ipv4 = subprocess.getoutput("curl -s ifconfig.me")
                    proxies = create_proxy(ipv4, ipv6_addresses, days)
                    
                    if num_proxies < 5:
                        await event.reply("Proxy đã tạo:\n" + "\n".join(proxies))
                    else:
                        with open('proxies.txt', 'w') as f:
                            for proxy in proxies:
                                f.write(f"{proxy}\n")
                        await event.reply(f"Đã tạo {num_proxies} proxy và lưu vào file proxies.txt")
                    
                    context['state'] = None
                except:
                    await event.reply("Định dạng không hợp lệ! Vui lòng nhập: số_lượng số_ngày (ví dụ: 5 7)")
            elif context.get('state') == 'giahan':
                try:
                    proxy, days = text.rsplit(' ', 1)
                    ipv4, port, user, password = proxy.split(':')
                    days = int(days)
                    
                    conn = sqlite3.connect('proxies.db')
                    c = conn.cursor()
                    c.execute("SELECT expiry_date FROM proxies WHERE ipv4=? AND port=? AND user=? AND password=?",
                              (ipv4, int(port), user, password))
                    result = c.fetchone()
                    if result:
                        old_expiry = datetime.datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
                        new_expiry = (old_expiry + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                        c.execute("UPDATE proxies SET expiry_date=? WHERE ipv4=? AND port=? AND user=? AND password=?",
                                  (new_expiry, ipv4, int(port), user, password))
                        conn.commit()
                        await event.reply(f"Đã gia hạn proxy {proxy} thêm {days} ngày.")
                    else:
                        await event.reply("Proxy không tồn tại!")
                    conn.close()
                    context['state'] = None
                except:
                    await event.reply("Định dạng không hợp lệ! Vui lòng nhập: IP:port:user:pass số_ngày")
            elif context.get('state') == 'xoa_le':
                try:
                    ipv4, port, user, password = text.split(':')
                    conn = sqlite3.connect('proxies.db')
                    c = conn.cursor()
                    c.execute("SELECT ipv6 FROM proxies WHERE ipv4=? AND port=? AND user=? AND password=?",
                              (ipv4, int(port), user, password))
                    result = c.fetchone()
                    if result:
                        ipv6 = result[0]
                        c.execute("DELETE FROM proxies WHERE ipv4=? AND port=? AND user=? AND password=?",
                                  (ipv4, int(port), user, password))
                        conn.commit()
                        
                        subprocess.run(['htpasswd', '-D', '/etc/squid/passwd', user])
                        
                        with open('/etc/squid/squid.conf', 'r') as f:
                            lines = f.readlines()
                        with open('/etc/squid/squid.conf', 'w') as f:
                            for line in lines:
                                if f"tcp_outgoing_address {ipv6}" not in line and f"http_port {port}" not in line:
                                    f.write(line)
                        subprocess.run(['systemctl', 'restart', 'squid'])
                        await event.reply(f"Đã xóa proxy {text}")
                    else:
                        await event.reply("Proxy không tồn tại!")
                    conn.close()
                    context['state'] = None
                except:
                    await event.reply("Định dạng không hợp lệ! Vui lòng nhập: IP:port:user:pass")
            elif context.get('state') == 'xoa_all':
                if text == 'Xac_nhan_xoa_all':
                    conn = sqlite3.connect('proxies.db')
                    c = conn.cursor()
                    c.execute("DELETE FROM proxies")
                    conn.commit()
                    conn.close()
                    
                    open('/etc/squid/passwd', 'w').close()
                    
                    with open('/etc/squid/squid.conf', 'w') as f:
                        f.write("""
acl localnet src 0.0.0.0/0
http_access allow localnet
http_access deny all
auth_param basic program /usr/lib64/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic children 5
auth_param basic realm Squid Basic Authentication
auth_param basic credentialsttl 2 hours
acl auth_users proxy_auth REQUIRED
http_access allow auth_users
""")
                    subprocess.run(['systemctl', 'restart', 'squid'])
                    await event.reply("Đã xóa tất cả proxy!")
                    context['state'] = None
                else:
                    await event.reply("Vui lòng nhập: Xac_nhan_xoa_all")
            
            client._user_data = context

        await client.run_until_disconnected()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
