import random
import string
import subprocess
import datetime
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
import sqlite3
import ipaddress
import time

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

# Telegram bot commands
def start(update: Update, context: CallbackContext):
    if update.message.from_user.id != 7550813603:
        update.message.reply_text("Bạn không có quyền sử dụng bot này!")
        return
    
    update.message.reply_text("Nhập prefix IPv6 (định dạng: 2401:2420:0:102f::/64 hoặc 2401:2420:0:102f:0000:0000:0000:0001/64):")
    context.user_data['state'] = 'prefix'

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == 'new':
        if 'prefix' not in context.user_data:
            query.message.reply_text("Vui lòng nhập prefix IPv6 trước bằng lệnh /start!")
            return
        query.message.reply_text("Nhập số lượng proxy và số ngày (định dạng: số_lượng số_ngày, ví dụ: 5 7):")
        context.user_data['state'] = 'new'
    elif query.data == 'xoa':
        keyboard = [
            [InlineKeyboardButton("Xóa proxy lẻ", callback_data='xoa_le'),
             InlineKeyboardButton("Xóa hàng loạt", callback_data='xoa_all')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.reply_text("Chọn kiểu xóa:", reply_markup=reply_markup)
    elif query.data == 'check':
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
        
        query.message.reply_text(f"Proxy chờ: {len(waiting)}\nProxy đã sử dụng: {len(used)}\nFile waiting.txt và used.txt đã được tạo.")
    elif query.data == 'giahan':
        query.message.reply_text("Nhập proxy và số ngày gia hạn (định dạng: IP:port:user:pass số_ngày):")
        context.user_data['state'] = 'giahan'
    elif query.data == 'xoa_le':
        query.message.reply_text("Nhập proxy cần xóa (định dạng: IP:port:user:pass):")
        context.user_data['state'] = 'xoa_le'
    elif query.data == 'xoa_all':
        query.message.reply_text("Xác nhận xóa tất cả proxy? (Nhập: Xac_nhan_xoa_all)")
        context.user_data['state'] = 'xoa_all'

def message_handler(update: Update, context: CallbackContext):
    if update.message.from_user.id != 7550813603:
        update.message.reply_text("Bạn không có quyền sử dụng bot này!")
        return
    
    state = context.user_data.get('state')
    text = update.message.text.strip()
    
    if state == 'prefix':
        if validate_ipv6_prefix(text):
            context.user_data['prefix'] = text
            keyboard = [
                [InlineKeyboardButton("/New", callback_data='new'),
                 InlineKeyboardButton("/Xoa", callback_data='xoa')],
                [InlineKeyboardButton("/Check", callback_data='check'),
                 InlineKeyboardButton("/Giahan", callback_data='giahan')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("Prefix IPv6 đã được lưu. Chọn lệnh:", reply_markup=reply_markup)
            context.user_data['state'] = None
        else:
            update.message.reply_text("Prefix IPv6 không hợp lệ! Vui lòng nhập lại:")
    elif state == 'new':
        try:
            num_proxies, days = map(int, text.split())
            if num_proxies <= 0 or days <= 0:
                update.message.reply_text("Số lượng và số ngày phải lớn hơn 0!")
                return
            prefix = context.user_data.get('prefix')
            if not prefix:
                update.message.reply_text("Vui lòng nhập prefix IPv6 trước bằng lệnh /start!")
                return
            ipv6_addresses = generate_ipv6_from_prefix(prefix, num_proxies)
            ipv4 = subprocess.getoutput("curl -s ifconfig.me")
            proxies = create_proxy(ipv4, ipv6_addresses, days)
            
            if num_proxies < 5:
                update.message.reply_text("Proxy đã tạo:\n" + "\n".join(proxies))
            else:
                with open('proxies.txt', 'w') as f:
                    for proxy in proxies:
                        f.write(f"{proxy}\n")
                update.message.reply_text(f"Đã tạo {num_proxies} proxy và lưu vào file proxies.txt")
            
            context.user_data['state'] = None
        except:
            update.message.reply_text("Định dạng không hợp lệ! Vui lòng nhập: số_lượng số_ngày (ví dụ: 5 7)")
    elif state == 'giahan':
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
                update.message.reply_text(f"Đã gia hạn proxy {proxy} thêm {days} ngày.")
            else:
                update.message.reply_text("Proxy không tồn tại!")
            conn.close()
            context.user_data['state'] = None
        except:
            update.message.reply_text("Định dạng không hợp lệ! Vui lòng nhập: IP:port:user:pass số_ngày")
    elif state == 'xoa_le':
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
                update.message.reply_text(f"Đã xóa proxy {text}")
            else:
                update.message.reply_text("Proxy không tồn tại!")
            conn.close()
            context.user_data['state'] = None
        except:
            update.message.reply_text("Định dạng không hợp lệ! Vui lòng nhập: IP:port:user:pass")
    elif state == 'xoa_all':
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
            update.message.reply_text("Đã xóa tất cả proxy!")
            context.user_data['state'] = None
        else:
            update.message.reply_text("Vui lòng nhập: Xac_nhan_xoa_all")

def main():
    init_db()
    updater = Updater("7022711443:AAEuPP6oTQl5H274gwyLhcy1hT_3cCEzifE", use_context=True, request_kwargs={'read_timeout': 6, 'connect_timeout': 7, 'con_pool_size': 1})
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    updater.start_polling(poll_interval=1.0)  # Giới hạn 1 request/giây
    updater.idle()

if __name__ == '__main__':
    main()
