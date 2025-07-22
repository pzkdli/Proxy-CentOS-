import random
import string
import subprocess
import datetime
import os
import time
import logging
import sqlite3
import ipaddress
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# Thiết lập logging để debug lỗi
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Cấu hình
IPV6_RANGE_PATH = "/root/ipv6_range.json"
SQUID_CONF = "/etc/squid/squid.conf"
SQUID_PASSWD = "/etc/squid/passwd"

# Kết nối cơ sở dữ liệu SQLite
def init_db():
    conn = sqlite3.connect('proxies.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS proxies
                 (ipv4 TEXT, port INTEGER, user TEXT, password TEXT, ipv6 TEXT, expiry_date TEXT, is_used INTEGER)''')
    conn.commit()
    conn.close()

# Tạo username (VTOANXXXY: 3 số + 1 chữ cái in hoa)
def generate_user():
    numbers = ''.join(random.choices(string.digits, k=3))
    letter = random.choice(string.ascii_uppercase)
    return f"VTOAN{numbers}{letter}"

# Tạo password (4 chữ cái in hoa)
def generate_password():
    return ''.join(random.choices(string.ascii_uppercase, k=4))

# Kiểm tra trạng thái Squid
def is_squid_running():
    result = subprocess.run("systemctl is-active squid", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if result.stdout.strip() != "active":
        logger.info("Squid is not running. Attempting to start Squid service...")
        subprocess.run("systemctl start squid", shell=True)
        time.sleep(2)  # Đợi 2 giây để Squid khởi động
        result = subprocess.run("systemctl is-active squid", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.stdout.strip() != "active":
            logger.error("Failed to start Squid service. Please check /var/log/squid/cache.log")
            return False
    return True

# Kiểm tra định dạng prefix IPv6
def validate_ipv6_prefix(prefix):
    try:
        ipaddress.IPv6Network(prefix, strict=False)
        return True
    except ValueError:
        logger.error(f"Prefix IPv6 không hợp lệ: {prefix}")
        return False

# Lấy prefix IPv6 từ file hoặc giao diện mạng
def get_ipv6_range():
    if os.path.exists(IPV6_RANGE_PATH):
        with open(IPV6_RANGE_PATH, "r") as f:
            data = json.load(f)
            ipv6_range = data.get("ipv6_range")
            if ipv6_range and validate_ipv6_prefix(ipv6_range):
                logger.info(f"Đã sử dụng dải IPv6 từ file: {ipv6_range}")
                return ipv6_range

    try:
        interface = subprocess.check_output(
            "ip link | grep '^[0-9]' | grep -v lo | awk -F': ' '{print $2}' | head -n 1",
            shell=True
        ).decode().strip()
        if not interface:
            logger.warning("Không tìm thấy giao diện mạng! Sử dụng eth0 làm mặc định.")
            interface = "eth0"
    except subprocess.CalledProcessError:
        logger.warning("Không thể tìm giao diện mạng! Sử dụng eth0 làm mặc định.")
        interface = "eth0"

    try:
        ipv6_range = subprocess.check_output(
            f"ip -6 addr show dev {interface} | grep inet6 | grep '/64' | awk '{{print $2}}' | head -n 1 | sed 's/\/64$//'",
            shell=True
        ).decode().strip()
        if ipv6_range:
            ipv6_range = str(ipaddress.IPv6Network(f"{ipv6_range}/64", strict=False))
            logger.info(f"Đã phát hiện dải IPv6: {ipv6_range}")
            with open(IPV6_RANGE_PATH, "w") as f:
                json.dump({"ipv6_range": ipv6_range}, f, indent=4)
            os.chmod(IPV6_RANGE_PATH, 0o600)
            return ipv6_range
    except subprocess.CalledProcessError:
        logger.error("Không thể lấy dải IPv6 từ giao diện mạng!")

    while True:
        logger.info("Không tìm thấy dải IPv6 /64 trên giao diện mạng.")
        ipv6_input = input("Nhập địa chỉ IPv6 đầy đủ (ví dụ: 2401:2420:0:102f:0000:0000:0000:0001/64): ")
        try:
            network = ipaddress.IPv6Network(ipv6_input, strict=False)
            ipv6_range = str(network)
            if validate_ipv6_prefix(ipv6_range):
                logger.info(f"Đã tách prefix IPv6: {ipv6_range}")
                with open(IPV6_RANGE_PATH, "w") as f:
                    json.dump({"ipv6_range": ipv6_range}, f, indent=4)
                os.chmod(IPV6_RANGE_PATH, 0o600)
                return ipv6_range
        except ValueError:
            logger.error("Địa chỉ IPv6 không hợp lệ! Vui lòng thử lại.")

# Tạo địa chỉ IPv6 ngẫu nhiên từ prefix
def generate_ipv6_from_prefix(prefix, num_addresses):
    try:
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
        
        # Gán địa chỉ IPv6 vào giao diện mạng
        interface = subprocess.check_output(
            "ip link | grep '^[0-9]' | grep -v lo | awk -F': ' '{print $2}' | head -n 1",
            shell=True
        ).decode().strip() or "eth0"
        for ipv6 in ipv6_addresses:
            subprocess.run(f"ip -6 addr add {ipv6}/64 dev {interface}", shell=True, check=False)
        
        return ipv6_addresses
    except Exception as e:
        logger.error(f"Lỗi khi tạo IPv6 từ prefix {prefix}: {e}")
        raise

# Tạo proxy mới với danh sách IPv6
def create_proxy(ipv4, ipv6_addresses, days):
    if not is_squid_running():
        raise Exception("Squid is not running and could not be started!")

    try:
        conn = sqlite3.connect('proxies.db')
        c = conn.cursor()
        
        c.execute("SELECT port FROM proxies")
        used_ports = [row[0] for row in c.fetchall()]
        
        proxies = []
        with open(SQUID_CONF, "r") as f:
            lines = f.readlines()
        http_access_index = next(i for i, line in enumerate(lines) if line.startswith("http_access ") or line.startswith("# Quy tắc truy cập"))
        
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
            
            # Thêm cấu hình Squid
            lines.insert(http_access_index, f"http_port [{ipv6}]:{port}\n")
            proxies.append((f"[{ipv6}]:{port}:{user}:{password}", ipv6))
        
        with open(SQUID_CONF, "w") as f:
            f.writelines(lines)
        
        # Thêm user/pass vào Squid
        for proxy, ipv6 in proxies:
            # Tách chuỗi proxy cẩn thận để xử lý IPv6
            ipv6_end = proxy.find("]:")
            user_pass = proxy[ipv6_end + 2:].split(":")
            user, password = user_pass[-2], user_pass[-1]
            subprocess.run(['htpasswd', '-b', SQUID_PASSWD, user, password], check=True)
        
        conn.commit()
        conn.close()
        
        # Tải lại cấu hình Squid
        result = subprocess.run(['squid', '-k', 'reconfigure'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode != 0:
            logger.error(f"Lỗi cấu hình Squid: {result.stderr}")
            raise Exception(f"Lỗi cấu hình Squid: {result.stderr}")
        
        logger.info(f"Đã tạo {len(proxies)} proxy với IPv6 tương ứng")
        return proxies
    except Exception as e:
        logger.error(f"Lỗi khi tạo proxy: {e}")
        raise

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
        c.execute("SELECT ipv4, port, user, password, is_used, ipv6 FROM proxies")
        proxies = c.fetchall()
        conn.close()
        
        waiting = [p for p in proxies if p[4] == 0]
        used = [p for p in proxies if p[4] == 1]
        
        with open('waiting.txt', 'w') as f:
            for p in waiting:
                f.write(f"[{p[5]}]:{p[1]}:{p[2]}:{p[3]} (IPv4: {p[0]})\n")
        with open('used.txt', 'w') as f:
            for p in used:
                f.write(f"[{p[5]}]:{p[1]}:{p[2]}:{p[3]} (IPv4: {p[0]})\n")
        
        try:
            context.bot.send_document(chat_id=update.effective_chat.id, document=open('waiting.txt', 'rb'), caption="Danh sách proxy chờ")
            context.bot.send_document(chat_id=update.effective_chat.id, document=open('used.txt', 'rb'), caption="Danh sách proxy đã sử dụng")
            query.message.reply_text(f"Proxy chờ: {len(waiting)}\nProxy đã sử dụng: {len(used)}\nFile waiting.txt và used.txt đã được gửi.")
        except Exception as e:
            logger.error(f"Lỗi khi gửi file waiting.txt/used.txt: {e}")
            query.message.reply_text(f"Proxy chờ: {len(waiting)}\nProxy đã sử dụng: {len(used)}\nLỗi khi gửi file: {e}")
    elif query.data == 'giahan':
        query.message.reply_text("Nhập proxy và số ngày gia hạn (định dạng: [IPv6]:port:user:pass số_ngày):")
        context.user_data['state'] = 'giahan'
    elif query.data == 'xoa_le':
        query.message.reply_text("Nhập proxy cần xóa (định dạng: [IPv6]:port:user:pass):")
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
                update.message.reply_text("Proxy đã tạo:\n" + "\n".join(p[0] + f" (IPv4: {ipv4})" for p in proxies))
            else:
                with open('proxies.txt', 'w') as f:
                    for proxy, ipv6 in proxies:
                        f.write(f"{proxy} (IPv4: {ipv4})\n")
                try:
                    context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=open('proxies.txt', 'rb'),
                        caption=f"Đã tạo {num_proxies} proxy",
                        timeout=30
                    )
                except Exception as e:
                    logger.error(f"Lỗi khi gửi file proxies.txt: {e}")
                    update.message.reply_text(f"Đã tạo {num_proxies} proxy nhưng lỗi khi gửi file: {e}\nFile proxies.txt đã được lưu trên hệ thống.")
            
            context.user_data['state'] = None
        except Exception as e:
            logger.error(f"Lỗi khi xử lý lệnh /New: {e}")
            update.message.reply_text(f"Định dạng không hợp lệ hoặc lỗi: {e}")
    elif state == 'giahan':
        try:
            proxy, days = text.rsplit(' ', 1)
            days = int(days)
            ipv6_end = proxy.find("]:")
            if ipv6_end == -1:
                update.message.reply_text("Định dạng không hợp lệ! Vui lòng nhập: [IPv6]:port:user:pass số_ngày")
                return
            ipv6 = proxy[1:ipv6_end]
            port, user, password = proxy[ipv6_end + 2:].split(':')
            
            conn = sqlite3.connect('proxies.db')
            c = conn.cursor()
            c.execute("SELECT expiry_date FROM proxies WHERE ipv6=? AND port=? AND user=? AND password=?",
                      (ipv6, int(port), user, password))
            result = c.fetchone()
            if result:
                old_expiry = datetime.datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
                new_expiry = (old_expiry + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                c.execute("UPDATE proxies SET expiry_date=? WHERE ipv6=? AND port=? AND user=? AND password=?",
                          (new_expiry, ipv6, int(port), user, password))
                conn.commit()
                update.message.reply_text(f"Đã gia hạn proxy {proxy} thêm {days} ngày.")
            else:
                update.message.reply_text("Proxy không tồn tại!")
            conn.close()
            context.user_data['state'] = None
        except:
            update.message.reply_text("Định dạng không hợp lệ! Vui lòng nhập: [IPv6]:port:user:pass số_ngày")
    elif state == 'xoa_le':
        try:
            ipv6_end = text.find("]:")
            if ipv6_end == -1:
                update.message.reply_text("Định dạng không hợp lệ! Vui lòng nhập: [IPv6]:port:user:pass")
                return
            ipv6 = text[1:ipv6_end]
            port, user, password = text[ipv6_end + 2:].split(':')
            
            conn = sqlite3.connect('proxies.db')
            c = conn.cursor()
            c.execute("SELECT ipv6 FROM proxies WHERE ipv6=? AND port=? AND user=? AND password=?",
                      (ipv6, int(port), user, password))
            result = c.fetchone()
            if result:
                c.execute("DELETE FROM proxies WHERE ipv6=? AND port=? AND user=? AND password=?",
                          (ipv6, int(port), user, password))
                conn.commit()
                
                subprocess.run(['htpasswd', '-D', SQUID_PASSWD, user], check=True)
                
                with open(SQUID_CONF, 'r') as f:
                    lines = f.readlines()
                with open(SQUID_CONF, 'w') as f:
                    for line in lines:
                        if f"http_port [{ipv6}]:{port}" not in line:
                            f.write(line)
                subprocess.run(['squid', '-k', 'reconfigure'], check=True)
                update.message.reply_text(f"Đã xóa proxy {text}")
            else:
                update.message.reply_text("Proxy không tồn tại!")
            conn.close()
            context.user_data['state'] = None
        except Exception as e:
            logger.error(f"Lỗi khi xóa proxy: {e}")
            update.message.reply_text(f"Định dạng không hợp lệ hoặc lỗi: {e}")
    elif state == 'xoa_all':
        if text == 'Xac_nhan_xoa_all':
            try:
                conn = sqlite3.connect('proxies.db')
                c = conn.cursor()
                c.execute("DELETE FROM proxies")
                conn.commit()
                conn.close()
                
                open(SQUID_PASSWD, 'w').close()
                
                with open(SQUID_CONF, 'w') as f:
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
                subprocess.run(['squid', '-k', 'reconfigure'], check=True)
                update.message.reply_text("Đã xóa tất cả proxy!")
                context.user_data['state'] = None
            except Exception as e:
                logger.error(f"Lỗi khi xóa tất cả proxy: {e}")
                update.message.reply_text(f"Lỗi khi xóa tất cả proxy: {e}")
        else:
            update.message.reply_text("Vui lòng nhập: Xac_nhan_xoa_all")

def main():
    init_db()
    updater = Updater("7022711443:AAHPixbTjnocW3LWgpW6gsGep-mCScOzJvM", use_context=True, request_kwargs={'read_timeout': 6, 'connect_timeout': 7, 'con_pool_size': 1})
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    updater.start_polling(poll_interval=1.0)
    updater.idle()

if __name__ == '__main__':
    main()
