import sys, random, socket, time, copy
from threading import Thread

# Command line arguments
n = len(sys.argv)
if n > 1:
    SELF_ID = int(sys.argv[1])
else:
    print("Client ID not given, generating random ID")
    SELF_ID = random.randint(1, 99)
print("Client ID:", SELF_ID)

UDP_IP = "127.0.0.1"
PORT_BASE = 10000
UDP_PORT = PORT_BASE + SELF_ID
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

homeID = None
CoA = None

def print_with_time(message: str):
    curTime = time.strftime("%H:%M:%S", time.localtime())
    print(curTime, "-", message)

def send_register_request(dstID, reqType='home'):
    message = "REQ\n" + reqType + '\n' + str(SELF_ID) # Add type header
    if reqType == 'foreign':
        if not homeID:
            print("Register home agent first")
            return
        message += '\n' + str(homeID)
    # Check if bytes-like object
    try:
        message = message.decode("utf-8")
    except AttributeError:
        pass
    data = str(SELF_ID) + ',' + str(dstID) + '\n' + message # Add addr header
    dataBytes = data.encode("utf-8")
    sock.sendto(dataBytes, (UDP_IP, PORT_BASE+dstID))
    print("Sent registration request")

def set_agent(reqType, agentID):
    global homeID
    global CoA
    agentID = int(agentID)
    if reqType == 'home':
        homeID = agentID
        CoA = agentID
        print("Set home agent", CoA)
    elif reqType == 'foreign' and homeID:
        CoA = agentID
        print("Set foreign agent", CoA)
    else:
        print("Cannot parse register request")


def send_to_id(message, srcID: int, dstID: int):
    # Check if bytes-like object
    try:
        message = message.decode("utf-8")
    except AttributeError:
        pass
    data = str(srcID) + ',' + str(dstID) + '\n' + message # Add addr header
    dataBytes = data.encode("utf-8")
    # Send to agent
    if CoA:
        port = PORT_BASE + CoA
    else:
        print('Client not connected to any agents')
        return
    sock.sendto(dataBytes, (UDP_IP, port))

def user_input():
    while True:
        user_input = input()
        command = user_input.split()
        if len(command) <= 0:
            continue

        # len 1
        elif command[0] == "exit":
            sys.exit()

        elif command[0] == "returnclient":
            global CoA, homeID
            CoA = homeID

        # len 3
        elif command[0] == "send":
            def help_send():
                print("send <ROUTER ID> <MESSAGE>")
            if len(command) != 3:
                help_send()
                continue
            try:
                int(command[1])
            except ValueError:
                help_send()
                continue
            message = "MSG\n" + command[2] # Add type header
            send_to_id(message, SELF_ID, int(command[1]))
        elif command[0] == "reg":
            def help_register():
                print('reg <ROUTER ID> <ha|fa>')
            if len(command) != 3:
                help_register()
                continue
            reqType = {'ha':'home', 'fa':'foreign'}
            try:
                int(command[1])
                if command[2].lower() not in reqType:
                    raise ValueError
            except ValueError:
                help_register()
                continue
            send_register_request(int(command[1]), reqType[command[2].lower()])
            
        else:
            print("Unknown command:", user_input)

def receiving():
    while True:
        try:
            data, addr = sock.recvfrom(1024) # BLOCKING
        except socket.timeout:
            continue
        # Drop packet
        if addr[1] == UDP_PORT:
            continue
        # if addr[1]-PORT_BASE != CoA: # No link
        #     continue
        # Parse data
        message = data.decode("utf-8")
        parts = message.split('\n', 2)
        if len(parts) != 3:
            print("Received something weird:", message)
            continue
        pktAddr, pktType, pktData = parts
        srcID, dstID = pktAddr.split(',')
        srcID, dstID = int(srcID), int(dstID)
        # Drop packet
        if dstID != SELF_ID:
            continue
        # Parse data according to type
        else:
            if pktType == "LSU":
                continue
            elif pktType == "MSG":
                print("Recv message from", str(srcID) + ':', pktData)
            elif pktType == "REP":
                reqType, agentID = pktData.split('\n', 1)
                set_agent(reqType, agentID)
            else:
                print("Unknown packet type from", srcID)

if __name__ == '__main__':
    t1 = Thread(target=receiving)
    t3 = Thread(target=user_input)
    t1.daemon = True
    t1.start()
    t3.start()
