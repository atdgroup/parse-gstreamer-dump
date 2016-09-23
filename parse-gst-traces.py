#! /usr/bin/python
# GStreamer scheduling parser
# Analyze GST traces and shows the time spent for each buffer at each element level.
#
# Usage: GST_DEBUG=*:2,GST_SCHEDULING:6,GST_PERFORMANCE:5 gst-launch-1.0 --gst-debug-no-color -e [PIPELINE] >foo 2>&1
#        ./parse-gst-traces.py foo
# Example of pipeline: videotestsrc num-buffers=200 ! "video/x-raw-yuv, format=(fourcc)NV12, width=1280, height=720, framerate=30/1" ! ducatih264enc profile=66 ! ducatih264dec! dri2videosink sync=false

# From: https://git.ti.com/glsdk/gst-plugin-ducati/blobs/3d2998f3f16f0742749ffeed197a6ef4edcb1476/tools/parse-gst-traces.py
# and modified for the CSI project.
# P Barber, Sep 2015.

import sys
import time
import fileinput
import re
import operator

from datetime import datetime

# Creates a datetime object from first 14 chars of d (up to us, excludes the ns part)
# which we expect to have the format "%H:%M:%S.%f"
def string_to_time (d):
  return datetime.strptime(d[0:14], "%H:%M:%S.%f")

def main():
  tr = dict()  # dict of key=frame time(pts) : value=list of (time, description) tuple entries 
  filt = dict()  # dict of key=frame time(pts) : value=dict ('filter name', list of tuples (time, elem, description))

  ### Parse stdin or any file on the command line
  for line in fileinput.input():	
    # Filter out GST traces from other output
    # NB \w = alpha numeric char, \s = white space char, + = one or more
    # Look for a time (\w text with ':'s and '.'s), space, text, space, text, space, text, space, anything
    m = re.match(r"([\w:.]+)[\s]+([\w]+)[\s]+([\w]+)[\s]+([\w]+)[\s]+(.*)",line)
    if m == None:
#      print line
      continue
 
    # Assign the text portions from the reg exp above into variables
    # tsr = time
    # pid = processor id
    # adr = address of ? - identifies the processing thread
    # sev = log message severity
    # msg = rest of line
    (tsr, pid, adr, sev, msg) = m.groups()

    # Parse GST_SCHEDULING traces from msg, try sink format element#:sink
    m = re.match(r"GST_SCHEDULING[\s]+gstpad.c:[\w]+:([\w_]+):<([A-Za-z0-9_]+)([0-9]+):([\w_]+)> calling chainfunction &[\w]+ with buffer buffer: ([\w]+), pts ([\w:.]+), dts ([\w:.]+), dur ([\w:.]+)", msg)

    # If no match, try for src pad format src:element#
    if m == None:
      m = re.match(r"GST_SCHEDULING[\s]+gstpad.c:[\w]+:([\w_]+):<([\w_]+):([A-Za-z0-9_]+)([0-9]+)> calling chainfunction &[\w]+ with buffer buffer: ([\w]+), pts ([\w:.]+), dts ([\w:.]+), dur ([\w:.]+)", msg)

    if m != None:
      
      # Assign vars from above reg exp
      # func = needs to be "gst_pad_chain_data_unchecked"
      # elem = element name
      # number = element number
      # pad = element pad
      # gstBuffer = buffer address
      # pts = frame presentation time stamp (when to present the data)
      # dts = frame decode time stamp (when to decode the data)
      # dur = frame presentation duration
      (func, elem, number, pad, gstBuffer, pts, dts, dur) = m.groups()

      # ignore a given element here
      if elem == "mpeg2dec":
        continue

      if func == "gst_pad_chain_data_unchecked":
        # Frames are identified by the pts (presentation time stamp), timings entered into the dictionary entry for that frame
        # If we have not seen this frame before, create an empty list for it
        if pts not in tr:
          tr[pts] = []
        # To the list for this frame, append a (time, description) tuple
        tr[pts].append((tsr, "Buffer %14s Thread %14s: %s%s:%s" % (gstBuffer, adr, elem, number, pad) ))


    # Look for special augment filter lines
    m = re.match(r"[\w\s.:]+:<([A-Za-z0-9_]+)>[\s]+gst_[\w]+_chain ([\w]+)[\w\s,]+pts[\s]+([0-9:.]+)", msg)

    if m != None:

      # Assign vars from above reg exp
      # elem = element name
      # event = expect 'started' or 'finished', but does not need to be I think
      # pts = frame presentation time stamp (when to present the data)
      (elem, event, pts) = m.groups()

      if elem not in filt:
        filt[elem] = dict()

      if pts not in filt[elem]:
        filt[elem][pts] = []
      filt[elem][pts].append((tsr, elem, "%s %s, pts %4s" % (elem, event, pts) ))


  ### End of stdin parsing

  # Display the results, frame per frame
  avg = cnt = total_count = 0
  filt_avg =  dict()
  filt_count =  dict()
  filt_name = dict()
  for elem in filt:
    filt_count[elem]=0
    filt_avg[elem]=0

  # tr has an item for every frame: tsb (frame time) : tfs (the list of (time, description) tuples)
  # iterate over frames
#  for tsb, tfs in tr.iteritems():
  for tsb, tfs in sorted(tr.items(), key=operator.itemgetter(0)):
    cnt +=1
    first = prev = string_to_time(tfs[0][0])    # get the time of the first item in tfs
    print "\n*** Frame no: %d, timestamp: %s" % (cnt, tsb)

    # iterate over the tfs list, el is the tuple
    for el in tfs:
      cur = string_to_time(el[0])
      if cur != prev:
        later = "(%6d us later)" % (cur - prev).microseconds
      else:
        later = "(    first event)"
      print "At %s %s %s" % (el[0][0:14], later, el[1])
      prev = cur
   
    total = cur - first
    print "*** Total: %6d us" % (total.microseconds)

    # Collect average stats
    if total.microseconds > 0:
      total_count +=1
      avg += total.microseconds

    for elem in filt:
      if tsb in filt[elem]:
        filt_name[elem]=filt[elem][tsb][0][1] 
        tfs = filt[elem][tsb]
        start = string_to_time(tfs[0][0])  # expect only 2 entries in the list, 1st is start
        stop = string_to_time(tfs[1][0])   # 2nd is stop
        filt_time = stop - start
        print "%s time %s us" % (tfs[0][1], filt_time.microseconds)
        if filt_time.microseconds > 0:
          filt_count[elem] += 1
          filt_avg[elem] += filt_time.microseconds


  # Display the totals
  if (total_count > 0):
    print "\n=-= Average: %6d us on %d frames" % (avg / total_count, total_count)
  else:
    print "\n=-= No valid frames"

  for elem in filt_count:
    if (filt_count[elem] > 0):
      print "=-= %s: %6d us on %d frames" % (filt_name[elem], filt_avg[elem] / filt_count[elem], filt_count[elem])

  return 0

if __name__ == '__main__':
  main()
