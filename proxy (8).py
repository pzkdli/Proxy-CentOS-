```python
import random
import string
import subprocess
import datetime
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
import sqlite3
import ipaddress

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

# Kiểm tra định dạng địa chỉ IPv6
def validate_ipv6_address(ipv6):
    try:
        ipaddress.IPv6Address(ipv6)
        return True
    except ValueError:
        return False

# Tạo proxy mới với danh sách IPv6
def create_proxy(ipv4, ipv6_addresses, days):
    conn = sqlite3.connect('proxies.db')
    c = conn.cursor()
    
    # Lấy danh sách port đã sử dụng
    c.execute("SELECT port FROM proxies")
    used_ports = [row[0] for row in c.fetchall()]
    
    proxies = []
    for ipv6 in ipv6_addresses:
        # Tạo port ngẫu nhiên
        while True:
            port = random.randint(1000, 60000)
            if port not in used_ports:
                used_ports.append(port)
                break
        
        user = generate_user()
        password = generate_password()
        expiry_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Thêm vào cơ sở dữ liệu
        c.execute("INSERT INTO proxies (ipv4, port, user, password, ipv6, expiry_date, is_used) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (ipv4, port, user, password, ipv6, expiry_date, 0))
        
        # Thêm cấu hình vào Squid
        with open('/etc/squid/squid.conf', 'a') as f:
            f.write(f"tcp_outgoing_address {ipv6}\n")
            f.write(f"http_port {port}\n")
        
        # Thêm user và password vào file passwd của Squid
        subprocess.run(['htpasswd', '-b', '/etc/squid/passwd', user, password])
        
        proxies.append(f"{ipv4}:{port}:{user}:{password}")
    
    conn.commit()
    conn.close()
    
    # Khởi động lại Squid
    subprocess.run(['systemctl', 'restart', 'squid'])
    
    return proxies

# Kiểm tra kết nối proxy (giả lập)
def check_proxy_usage(ipv4, port):
    # Giả lập kiểm tra kết nối, thay bằng phân tích log Squid nếu cần
    return random.choice([True, False])

# Telegram bot commands
def start(update: Update, context: CallbackContext):
    if update.message.from_user.id != 7550813603:
        update.message.reply_text("Bạn không có quyền sử dụng bot này!")
        return
    
    keyboard = [
        [InlineKeyboardButton("/New", callback_data='new'),
         InlineKeyboardButton("/Xoa", callback_data='xoa')],
        [InlineKeyboardButton("/Check", callback_data='check'),
         InlineKeyboardButton("/Giahan", callback_data='giahan')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Chọn lệnh:", reply_markup=reply_markup)

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == 'new':
        query.message.reply_text("Nhập số ngày và danh sách địa chỉ IPv6 (mỗi địa chỉ trên một dòng):")
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
        query.message.reply_text("Nhập proxy cần xóa (định dạng: IP:port:user:(pass):")
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
    
    if state == 'new':
        try:
            lines = text.split('\n')
            days = int(lines[0])
            ipv6_addresses = [ip.strip() for ip in lines[1:] if ip.strip()]
            
            # Kiểm tra định dạng IPv6
            for ipv6 in ipv6_addresses:
                if not validate_ipv6_address(ipv6):
                    update.message.reply_text(f"Địa chỉ IPv6 không hợp lệ: {ipv6}")
                    return
            
            ipv4 = subprocess.getoutput("curl -s ifconfig.me")  # Lấy IPv4 của VPS
            proxies = create_proxy(ipv4, ipv6_addresses, days)
            update.message.reply_text("Proxy đã tạo:\n" + "\n".join(proxies))
            context.user_data['state'] = None
        except:
            update.message.reply_text("Định dạng không hợp lệ! Nhập số ngày ở dòng đầu tiên, sau đó là danh sách địa chỉ IPv6 (mỗi địa chỉ trên một dòng).")
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
                
                # Xóa user khỏi file passwd
                subprocess.run(['htpasswd', '-D', '/etc/squid/passwd', user])
                
                # Xóa cấu hình khỏi Squid
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
            
            # Xóa tất cả user trong file passwd
            open('/etc/squid/passwd', 'w').close()
            
            # Khôi phục file cấu hình Squid
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
    updater = Updater("7022711443:AAG2kU-TWDskXqFxCjap1DGw2jjji2HE2Ac", use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
```