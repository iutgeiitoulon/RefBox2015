#!/usr/bin/env python
# 2016-11-29 Jan Feitsma
#
# Description: load a MSL log file in memory and browse through it.
# TODO statistics


from pygame import time
import json
from zipfile import ZipFile
import socket
from logMapping import MSLLog2AudienceClientLog
import sys

# binary search that searches nearest elem in array
def bsearch(array, elem):
    l = 0
    r = len(array) - 1
    m = (l + r) / 2
    while True:
        if r < l:
            break
        m = (l + r) / 2
        if array[m] < elem:
            l = m + 1
        elif array[m] > elem:
            r = m - 1
        else:
            # exact match
            return array[m]
    # fuzzy match
    diffs = {}
    diffs[m] = abs(elem - array[m])
    if m < len(array)-2: # get right element of m
        diffs[m+1] = abs(elem - array[m+1])
    if m > 1: # get right element of m
        diffs[m-1] = abs(elem - array[m-1])

    minval = sys.maxint
    minindex = -1
    for k,v in diffs.iteritems():
        if v < minval:
            minindex = k
            minval = v

    return array[minindex]


class MatchLogPublisher():
    """
    This class can load a MSL zip file and stimulate AudienceClient.
    It needs a playback object to control time, speed and offset (slider etc).
    """
    def __init__(self, zipfile):
        # initialize self
        self.buffer = None
        self.frequency = 20.0
        # load the bag file
        self.loadZipFile(zipfile)
        
    def host(self):
        HOST = ''
        PORT = 12345
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.bind((HOST, PORT))
        self.s.listen(1)
        conn,addr = self.s.accept()
        return conn,addr

    def loadZipFile(self, zipfile):
        print "Loading {0}...".format(zipfile)

        with ZipFile(zipfile, 'r') as mslzip:
            files = mslzip.filelist

            # find files and parse json
            for f in files:
                if f.filename.endswith(".A.msl"):
                    json_a = json.loads(mslzip.read(f.filename).encode("utf-8"))
                elif f.filename.endswith(".B.msl"):
                    json_b = json.loads(mslzip.read(f.filename).encode("utf-8"))

        self.tStart = 1e99
        self.tEnd = -1e99

        if json_a != None:
            self.data_a, self.meta_a = self.createData(json_a)
            print "Team A loaded, meta:", self.meta_a
            self.tStart = min(self.tStart, self.meta_a['tStart'])
            self.tEnd = max(self.tEnd, self.meta_a['tEnd'])

        if json_b != None:
            self.data_b, self.meta_b = self.createData(json_b)
            print "Team B loaded, meta:", self.meta_b
            self.tStart = min(self.tStart, self.meta_b['tStart'])
            self.tEnd = max(self.tEnd, self.meta_b['tEnd'])
            
        # convert to float [seconds]
        self.tStart = float(self.tStart * 1e-3)
        self.tEnd = float(self.tEnd * 1e-3)
        
        self.tElapsed = self.tEnd - self.tStart

    def createData(dataself, json_data):
        data = {}
        meta = {}
        first = True

        for entry in json_data:
            time = long(entry['timestamp'])
            data[time] = entry
            if first:
                tStart = time
                tEnd = time
                first = False
            else:
                tStart = min(tStart, time)
                tEnd = max(tEnd, time)

        meta['tElapsed'] = tEnd - tStart
        meta['tStart'] = tStart
        meta['tEnd'] = tEnd

        return (data, meta)
        
    def advance(self, t):
        """
        Advance to given timestamp (relative) as float, in seconds.
        """
        # translate relative to absolute time
        t = long(1000*(t + self.tStart))
        # temporary: return last message
        self.buffer = (self.data_a[self.data_a.keys()[-1]], self.data_b[self.data_b.keys()[-1]])
        
    def run(self, playback):
        print 'sorting timestamps'
        keys_a = sorted(self.data_a.keys())
        keys_b = sorted(self.data_b.keys())
        done = False

        dt = 1.0 / self.frequency
        print "setup load"
        conn, addr = self.host()
        print "starting loop"
        
        while not done:
            # get timestamp from playback
            t = playback.updateTime(dt)

            # advance and publish
            #self.advance(t)
            key_a = bsearch(keys_a, long ((t+self.tStart)*1000.0))
            entry_a = self.data_a[key_a]
            key_b = bsearch(keys_b, long((t+self.tStart)*1000.0))
            entry_b = self.data_b[key_b]
            self.buffer = (entry_a, entry_b) # TODO this should move into advance() for reuse in statistics
            # convert buffer json
            buf = MSLLog2AudienceClientLog(self.buffer[0], self.buffer[1])
            # set time stamp
            buf['gameTime'] = "%02d:%02d" % (int(t / 60), int(t) % 60)
            # client expects null termination (!)
            bufStr = json.dumps(buf) + "\0"
            # send msg buffer
            conn.sendall(bufStr)
            # sleep
            time.Clock().tick_busy_loop(self.frequency)
            if t > self.tElapsed:
                done = True

        conn.close()
