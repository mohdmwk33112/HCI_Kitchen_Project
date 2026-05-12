import socket
import threading

HOST = "0.0.0.0"
PORT = 65434

def receive_messages(conn):
    if not hasattr(receive_messages, "buffer"):
        receive_messages.buffer = ""
    
    try:
        while "\n" not in receive_messages.buffer:
            data = conn.recv(1024)
            if not data:
                print("C# disconnected.")
                return None
            receive_messages.buffer += data.decode("utf-8")

        msg, receive_messages.buffer = receive_messages.buffer.split("\n", 1)
        print("C#:", msg)

        if msg.lower() == "q":
            return "q"

        return msg

    except Exception as e:
        print("Receive error:", e)
        return None


def connect_to_server(HOST=HOST, PORT=PORT):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(1)

    print(f"Python server listening on {HOST}:{PORT}")
    conn, addr = server.accept()
    print("Connected by:", addr)
    return conn, server
def main():

    conn, server = connect_to_server()
    recv_thread = threading.Thread(target=receive_messages, args=(conn,), daemon=True)
    recv_thread.start()

    try:
        while True:
            msg = input("Python: ")
            conn.sendall((msg + "\n").encode("utf-8"))

            if msg.lower() == "q":
                break
    except Exception as e:
        print("Send error:", e)
    finally:
        conn.close()
        server.close()

if __name__ == "__main__":
    main()