"""
验证：9600 和 115200 波特率下，TRS:DATA? 返回的格式是否不同
"""
import serial, threading, queue, time

def test_baud(baud):
    rx_buf = bytearray()
    rx_q = queue.Queue()
    last_rx = [0.0]
    stop = threading.Event()

    def rx_loop(ser):
        while not stop.is_set():
            try: data = ser.read(4096)
            except: break
            if data:
                rx_buf.extend(data)
                last_rx[0] = time.monotonic()
            else:
                if rx_buf and (time.monotonic() - last_rx[0]) * 1000 >= 400:
                    rx_q.put(bytes(rx_buf))
                    rx_buf.clear()

    print(f'\n{"="*50}')
    print(f'测试 {baud} bps')
    print(f'{"="*50}')

    ser = serial.Serial('COM4', baud, timeout=0.05)
    threading.Thread(target=rx_loop, args=(ser,), daemon=True).start()
    time.sleep(0.3)

    # 加载配置
    ser.write(b'mmem:load:trs 2\r\n')
    try:
        pkt = rx_q.get(timeout=15)
        print(f'配置文件: {len(pkt)} 字节')
    except queue.Empty:
        print('配置文件加载超时')
        stop.set(); ser.close(); return

    # 触发
    ser.write(b'*TRG\r\n')
    t0 = time.time()
    while True:
        time.sleep(0.4)
        ser.write(b'*OPC?\r\n')
        try:
            p = rx_q.get(timeout=1)
            if b'1' in p:
                print(f'测试完成 ({time.time()-t0:.1f}s)')
                break
        except queue.Empty:
            pass
        if time.time()-t0 > 30:
            print('超时'); break

    time.sleep(0.3)
    while not rx_q.empty(): rx_q.get_nowait()

    # 读结果
    ser.write(b'TRS:DATA?\r\n')
    try:
        pkt = rx_q.get(timeout=10)
    except queue.Empty:
        print('TRS:DATA? 超时'); stop.set(); ser.close(); return

    print(f'TRS:DATA? 收到: {len(pkt)} 字节')
    print(f'前20字节 hex: {pkt[:20].hex()}')

    # 判断格式
    if b'#\x01' in pkt[:5]:
        print('格式: 二进制 (#\\x01 开头)')
    elif b';' in pkt and b',' in pkt:
        print('格式: CSV 文本 (含分号和逗号)')
        # 打印前200字符
        print(f'内容预览: {pkt[:200].decode("ascii", errors="replace")}')
    else:
        print(f'格式: 未知')
        print(f'可打印内容: {pkt[:100].decode("ascii", errors="replace")}')

    stop.set(); ser.close()

# 先测 115200（当前设置）
test_baud(115200)

# 再测 9600
input('\n请在仪器上把波特率改回 9600，然后按回车...')
test_baud(9600)
