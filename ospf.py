import sys, random, socket, time, copy
from threading import Thread
debug = 0

# Command line arguments
n = len(sys.argv)
if n > 1:
    SELF_ID = int(sys.argv[1])
else:
    print("Router ID not given, generating random ID")
    SELF_ID = random.randint(1, 99)
print("Router ID:", SELF_ID)

# Socket
UDP_IP = "127.0.0.1"
PORT_BASE = 10000
UDP_PORT = PORT_BASE + SELF_ID
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

# Data
class Neighbour:
    def __init__(self):
        self.state = "Down"
        self.lastDBD = {}

class Routing:
    def __init__(self):
        self.table = {} # Routing table {dstID: [nextHopID, cost]}

    def get_next_hop(self, dstID: int) -> int:
        if dstID not in self.table:
            return None
        else:
            return self.table[dstID][0]

    def calc_spf(self, lsdb):
        nodes = {SELF_ID: [None, 0]} # {ID: [prvNode, cost]}
        visited = []
        unvisited = [SELF_ID]
        self.__dijkstra(SELF_ID, nodes, visited, unvisited, lsdb)
        # print("nodes:", nodes)
        # print("visited:", visited)
        # print("unvisited:", unvisited)
        visitedNodes = [[i, nodes[i]] for i in visited]
        for dstID, node in visitedNodes: # Update routing table
            if dstID == SELF_ID:
                continue
            cost = node[1]
            nxtHopID = self.__calc_next_hop(nodes, dstID) # Calc next hop
            if dstID not in self.table: # New route
                print_with_time("add route " + str(dstID) + ' ' + str(nxtHopID) + ' ' + str(cost))
            elif self.table[dstID] != [nxtHopID, cost]: # Route changed
                print_with_time("update route " + str(dstID) + ' ' + str(nxtHopID) + ' ' + str(cost))
            self.table[dstID] = [nxtHopID, cost]
        idDel = []
        for id in self.table: # Find broken routes
            if id not in nodes:
                idDel.append(id)
        for id in idDel:
            del self.table[id]
            print_with_time("remove route " + str(dstID))
        # print(self.table)

    def __dijkstra(self, curID, nodes, visited, unvisited, lsdb):
        try:
            curNode = lsdb[curID]
        except KeyError: # No such key
            pass
        else: # Only perform if neighbour LSA in LSDB
            for id, cost in curNode[2].items(): # linkTable
                if id in nodes:
                    if nodes[curID][1] + cost < nodes[id][1]: # If current path cost cheaper than previous path
                        nodes[id] = [curID, nodes[curID][1] + cost]
                else:
                    unvisited.append(id)
                    nodes[id] = [curID, nodes[curID][1] + cost]
        visited.append(curID)
        try:
            unvisited.remove(curID)
        except ValueError:
            pass
        if not unvisited: # Visited all nodes
            return
        closestID = self.__closest_ID(nodes, unvisited)
        self.__dijkstra(closestID, nodes, visited, unvisited, lsdb)

    def __closest_ID(self, nodes, unvisited):
        nodeList = [[i, nodes[i]] for i in unvisited]
        nodeList.sort(key=lambda x: x[1][1]) # Sort by cost
        if not nodeList:
            return None
        else:
            return nodeList[0][0]

    def __calc_next_hop(self, nodes, dstID):
        curID = dstID
        prevID = nodes[dstID][0]
        while prevID != SELF_ID: # Backtrack to self -> nextHop
            curID = prevID
            prevID = nodes[curID][0]
        return curID


nbTable = {} # Neighbour table {ID: Neighbour}
linkTable = {} # Link table {ID: Cost}
sysLSA = [SELF_ID, 0, linkTable, int(time.time())] # [ID, Seq, linkTable, lastUpdateTime]
sysLSDB = {SELF_ID: sysLSA} # Collection of LSA from routers including self {ID: LSA}
sysDBD = {} # {ID, Seq}
sysRT = Routing() 
STATES = ("Down", "Init", "Exchange", "Full") # Neighbour states

# Mutual exclusion lock for tables
lsdbLock = 0
dbdLock = 0

##### Neighbour table #####
def set_nb(id: int, state: str):
    global nbTable
    global linkTable
    id = int(id)
    if state not in STATES:
        print("Invalid state:", state)
        return
    if id not in linkTable:
        return
    elif id not in nbTable:
        nbTable[id] = Neighbour()
    elif nbTable[id].state != state:
        print_with_time("update neighbor state " + str(id) + ' ' + state)
        nbTable[id].state = state

def remove_nb(nbID: int):
    global nbTable
    nbID = int(nbID)
    if nbID not in nbTable:
        return
    del nbTable[nbID]
    print_with_time("remove neighbor " + str(nbID))

##### Links #####
def set_link(id: int, cost: int):
    global sysLSA
    id = int(id)
    cost = int(cost)
    if id not in linkTable:
        print("Link not found")
        return
    print_with_time("update neighbour " + str(id) + ' ' + str(cost))
    # Update link cost in LSA
    sysLSA[1] += 1
    sysLSA[2][id] = cost
    sysLSA[3] = int(time.time())
    print_with_time("update LSA " + str(SELF_ID) + ' ' + str(sysLSA[1]))
    # Flood updated LSA
    lsu = [sysLSA]
    send_LSU(lsu, "flood")
    attempt_calc_spf()
    
def add_link(id: int, cost: int):
    global sysLSA
    id = int(id)
    cost = int(cost)
    if id in linkTable:
        print("Link already exists")
        return
    # Add link cost
    sysLSA[2][id] = cost
    # Add to neighbour table
    set_nb(id, "Down")
    print_with_time("add neighbour " + str(id) + ' ' + str(cost))
    # Add link cost in LSA
    sysLSA[1] += 1
    sysLSA[3] = int(time.time())
    print_with_time("update LSA " + str(SELF_ID) + ' ' + str(sysLSA[1]))
    # Flood updated LSA
    lsu = [sysLSA]
    send_LSU(lsu, "flood")
    attempt_calc_spf()

def remove_link(id):
    global sysLSA
    remove_nb(id)
    if id not in sysLSA[2]:
        print("Link not found")
        return
    del sysLSA[2][id]
    sysLSA[1] += 1
    sysLSA[3] = int(time.time())
    print_with_time("update LSA " + str(SELF_ID) + ' ' + str(sysLSA[1]))
    # Flood updated LSA
    lsu = [sysLSA]
    send_LSU(lsu, "flood")
    attempt_calc_spf()

##### HELLO #####
def send_HELLO(id: int):
    id = int(id)
    message = "HELLO\n"
    if nbTable[id].state == "Down":
        message += "init"
    else:
        message += "received"
    send_to_id_noRT(message, SELF_ID, id)

##### DBD ######
def update_nb_DBD(id: int, DBD):
    global nbTable
    id = int(id)
    if id not in nbTable:
        print("Neighbour not found for DBD")
        return
    nbTable[id].lastDBD = copy.deepcopy(DBD)

def update_sysDBD(): # sysDBD is only updated here with reference to sysLSDB
    global sysLSDB
    global sysDBD
    global dbdLock
    while dbdLock: # mutex
        continue
    dbdLock = 1 # mutex lock
    sysDBD.clear()
    for id, lsa in sysLSDB.items():
        id = int(id)
        sysDBD[id] = lsa[1]
    dbdLock = 0 # mutex unlock

def compare_DBD(DBD) -> tuple: # Return tuple of ID's to send LSR
    global sysLSDB
    global lsdbLock
    update_sysDBD()
    lsr = []
    while lsdbLock: #mutex
        continue
    lsdbLock = 1 # mutex lock
    for lsaID, lsaSeq in DBD.items():
        if lsaID not in sysLSDB: # missing
            lsr.append(lsaID)
        elif sysLSDB[lsaID][1] < lsaSeq: # needs update
            lsr.append(lsaID)
    lsdbLock = 0 # mutex unlock
    return tuple(lsr)

def send_DBD(id: int=0):
    global sysDBD
    update_sysDBD() # update sysDBD
    id = int(id)
    message = "DBD\n"
    if not sysDBD: # empty ## May be redundant
        return
    for lsaID, lsaSeq in sysDBD.items():
        message += str(lsaID) + ',' + str(lsaSeq) + '\n'
    message = message.strip('\n')
    send_to_id_noRT(message, SELF_ID, id)

##### LSR/LSU #####
def send_LSR(lsr, id: int):
    id = int(id)
    message = "LSR\n"
    for reqID in lsr:
        message += str(reqID) + '\n'
    message = message.strip('\n')
    send_to_id_noRT(message, SELF_ID, id)

def send_LSU(lsu, mode="single", dstID: int=0):
    dstID = int(dstID)
    # Encode as csv
    message = "LSU\n"
    for lsa in lsu: # LSU is list
        temp = str(lsa[0]) + ',' + str(lsa[1]) + ',' # ID, Seq
        for linkID, cost in lsa[2].items(): # LSA
            temp += str(linkID) + ':' + str(cost) + ';'
        temp = temp.strip(';')
        temp += '\n'
        message += temp
    message = message.strip(";\n")
    # Single
    if mode == "single":
        send_to_id_noRT(message, SELF_ID, dstID)
    # Flood
    elif mode == "flood":
        idList = list(nbTable.keys())
        try:
            idList.remove(SELF_ID)
        except ValueError:
            pass
        for linkID in idList:
            send_to_id_noRT(message, SELF_ID, linkID)

##### LSDB #####
def update_sysLSDB(lsu):
    global sysLSDB
    global lsdbLock
    updatedLSU = []
    while lsdbLock: # mutex
        continue
    lsdbLock = 1 # mutex lock
    for lsa in lsu:
        id = lsa[0]
        lsa.append(int(time.time()))
        if id in sysLSDB:
            if sysLSDB[id][1] >= lsa[1]:
                continue
            print_with_time("update LSA " + str(id) + ' ' + str(lsa[1]))
        else:
            print_with_time("add LSA " + str(id) + ' ' + str(lsa[1]))
        sysLSDB[id] = copy.deepcopy(lsa)
        updatedLSU.append(lsa)
    if debug: print(sysLSDB)
    lsdbLock = 0 # mutex unlock
    if updatedLSU: # If any changes occur
        attempt_calc_spf()
        send_LSU(updatedLSU, "flood") # Flood updated LSU

##### System #####
def print_with_time(message: str):
    curTime = time.strftime("%H:%M:%S", time.localtime())
    print(curTime, "-", message)

def attempt_calc_spf():
    global sysLSDB
    global lsdbLock
    global sysRT
    while lsdbLock: # mutex
        continue
    lsdbLock = 1 # mutex lock
    sysRT.calc_spf(sysLSDB) # Calculate shortest path
    lsdbLock = 0 # mutex unlock

def send_to_id(message, srcID: int, dstID: int, senderID: int=None):
    global sysRT
    # Check if bytes-like object
    try:
        message = message.decode("utf-8")
    except AttributeError:
        pass
    data = str(srcID) + ',' + str(dstID) + '\n' + message # Add addr header
    dataBytes = data.encode("utf-8")
    # spf
    nextHopID = sysRT.get_next_hop(dstID)
    if nextHopID is None or nextHopID == senderID: # Avoid return to sender
        return
    port = PORT_BASE + nextHopID
    sock.sendto(dataBytes, (UDP_IP, port))
    if debug: print("=== SENT ===", data, "==========", sep='\n')

def send_to_id_noRT(message, srcID: int, dstID: int):
    global sysRT
    # Check if bytes-like object
    try:
        message = message.decode("utf-8")
    except AttributeError:
        pass
    data = str(srcID) + ',' + str(dstID) + '\n' + message # Add addr header
    dataBytes = data.encode("utf-8")
    if dstID not in linkTable:
        return
    port = PORT_BASE + dstID
    sock.sendto(dataBytes, (UDP_IP, port))
    if debug: print("=== SENT NO RT ===", data, "==========", sep='\n')
        
def user_input():
    while True:
        user_input = input()
        command = user_input.split()
        if len(command) <= 0:
            continue

        # len 1
        elif command[0] == "exit":
            sys.exit()

        # len 2
        elif command[0] == "rmlink":
            def rmlink_help():
                print("rmlink <ROUTER ID>")
            if len(command) != 2:
                rmlink_help()
                continue
            try:
                remove_link(int(command[1]))
            except ValueError:
                rmlink_help()

        # len 3
        elif command[0] == "setlink":
            def help_setlink():
                print("setlink <ROUTER ID> <COST>")
            if len(command) != 3:
                help_setlink()
                continue
            try:
                set_link(int(command[1]), int(command[2]))
            except ValueError:
                help_setlink()
                
        elif command[0] == "addlink":
            def help_addlink():
                print("addlink <ROUTER ID> <COST>")
            if len(command) != 3:
                help_addlink()
                continue
            try:
                if int(command[1]) == SELF_ID:
                    print("Cannot add link to self")
                    continue
                add_link(int(command[1]), int(command[2]))
            except ValueError:
                help_addlink()

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
            
        elif command[0] == "links":
            global linkTable
            print(linkTable)

        elif command[0] == "rt":
            global sysRT
            print(sysRT.table)

        elif command[0] == "nb":
            global nbTable
            for key, nb in nbTable.items():
                print(key, nb.state)

        else:
            print("Unknown command:", user_input)

def receiving():
    global nbTable
    global linkTable
    global sysLSDB
    global sysRT
    while True:
        try:
            data, addr = sock.recvfrom(1024) # BLOCKING
        except socket.timeout:
            continue
        # Drop packet
        if addr[1] == UDP_PORT:
            continue
        if addr[1]-PORT_BASE not in linkTable: # No link
            continue
        # Parse data
        message = data.decode("utf-8")
        parts = message.split('\n', 2)
        if len(parts) != 3:
            print("Received something weird:", message)
            continue
        pktAddr, pktType, pktData = parts
        srcID, dstID = pktAddr.split(',')
        srcID, dstID = int(srcID), int(dstID)
        # Forward packet
        if dstID != SELF_ID:
            if pktType in ('MSG', 'TUN', 'AGENT'):
                print("Forward message from", str(srcID), "to", str(dstID) + ':', pktData)
                message = pktType + '\n' + pktData
                send_to_id(message, srcID, dstID, senderID=addr[1]-PORT_BASE)
                continue
        # Parse data according to type
        else:
            if pktType == "HELLO":
                if pktData == "init":
                    set_nb(srcID, "Init")
                elif pktData == "received":
                    if nbTable[srcID].state != "Full":
                        set_nb(srcID, "Exchange") 
                    send_DBD(srcID) # In case last DBD not received
                    
            elif pktType == "DBD":
                if debug: print("DBD debug:", pktData)
                pktDBD = {}
                for i in pktData.split('\n'):
                    dbdID, dbdSeq = i.split(',')
                    pktDBD[int(dbdID)] = int(dbdSeq)
                lsr = compare_DBD(pktDBD)
                if lsr:
                    send_LSR(lsr, srcID)
                else: 
                    if nbTable[srcID].state != "Full":
                        send_DBD(srcID) # Last DBD
                    set_nb(srcID, "Full")
                    
            elif pktType == "LSR":
                if debug: print("LSR debug:", pktData)
                idList = pktData.split('\n')
                lsu = []
                for id in idList:
                    lsu.append(sysLSDB[int(id)])
                send_LSU(lsu, "single", srcID)

            elif pktType == "LSU":
                if debug: print("LSU debug:", pktData)
                pktLSU = []
                for i in pktData.split('\n'): # LSA per router
                    id, seq, strLink = i.split(',')
                    id, seq = int(id), int(seq)
                    updateLink = {}
                    for j in strLink.split(';'): # For each link in linkTable
                        linkID, linkCost = j.split(':') # Link table dict (ID, Cost)
                        updateLink[int(linkID)] = int(linkCost)
                    pktLSU.append([id, seq, updateLink])
                if debug: print("pktLSU debug:", pktLSU)
                update_sysLSDB(pktLSU)

            elif pktType == "MSG":
                print("Recv message from", str(srcID) + ':', pktData)

            else:
                print("Unknown packet type from", srcID)

def system():
    global nbTable
    global sysLSA
    global sysLSDB
    global lsdbLock
    global sysRT
    while True:
        curTime = int(time.time())
        # Check each LSA for refresh / timeout
        lsu = []
        idDel = []
        while lsdbLock: # mutex
            continue
        lsdbLock = 1 # mutex lock
        if curTime - sysLSA[3] >= 15: # Refresh self LSA
            sysLSA[1] += 1 # Seq += 1
            sysLSA[3] = int(time.time())
            print_with_time("update LSA " + str(SELF_ID) + ' ' + str(sysLSA[1]))
            lsu.append(sysLSA) # add to LSU to flood
            send_LSU(lsu, "flood")
        for id, lsa in sysLSDB.items():
            if curTime - lsa[3] >= 30: # Timeout
                idDel.append(id)
        try:
            idDel.remove(SELF_ID) # Ignore self ID
        except ValueError:
            pass
        for id in idDel:
            del sysLSDB[id]
            print_with_time("remove LSA " + str(id))
            set_nb(id, "Down")
        lsdbLock = 0 # mutex unlock

        # LSU
        if lsu or idDel: # not empty
            attempt_calc_spf()

        # Interval task
        for id in nbTable.keys():
            id = int(id)
            if nbTable[id].state != "Full":
                send_HELLO(id)
            if nbTable[id].state == "Exchange":
                send_DBD(id)

        # 1 second interval
        time.sleep(1)



if __name__ == '__main__':
    t1 = Thread(target=receiving)
    t2 = Thread(target=system)
    t3 = Thread(target=user_input)
    t1.daemon = True
    t2.daemon = True
    t1.start()
    t2.start()
    t3.start()