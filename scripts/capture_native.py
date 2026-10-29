"""Capture only the visible assistant shape, masking the desktop outside its native region."""
import ctypes
from ctypes import wintypes
import struct
from PIL import Image, ImageDraw, ImageGrab

user=ctypes.windll.user32
gdi=ctypes.windll.gdi32
user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
user.GetWindowRgn.argtypes=[wintypes.HWND,wintypes.HRGN]
gdi.CreateRectRgn.restype=wintypes.HRGN
gdi.GetRegionData.argtypes=[wintypes.HRGN,wintypes.DWORD,ctypes.c_void_p]
gdi.DeleteObject.argtypes=[wintypes.HGDIOBJ]

def artwork(hwnd,envelope=None):
    rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
    bounds=(rect.left,rect.top,rect.right,rect.bottom)
    width,height=rect.right-rect.left,rect.bottom-rect.top
    image=ImageGrab.grab(bbox=bounds,all_screens=True).convert('RGBA')
    mask=Image.new('L',(width,height),0);draw=ImageDraw.Draw(mask)
    region=gdi.CreateRectRgn(0,0,0,0)
    try:
        if user.GetWindowRgn(hwnd,region):
            length=gdi.GetRegionData(region,0,None);buffer=ctypes.create_string_buffer(length)
            gdi.GetRegionData(region,length,buffer);count=struct.unpack_from('<I',buffer.raw,8)[0]
            for index in range(count):
                left,top,right,bottom=struct.unpack_from('<4i',buffer.raw,32+16*index)
                draw.rectangle((left,top,right-1,bottom-1),fill=255)
        elif width<=112 and height<=112:
            scale=width/56;draw.ellipse(tuple(int(v*scale) for v in (8,8,48,48)),fill=255)
            draw.rounded_rectangle(tuple(int(v*scale) for v in (40,0,56,16)),radius=int(8*scale),fill=255)
        else:
            draw.rounded_rectangle((0,0,width-1,height-1),radius=22,fill=255)
    finally:
        gdi.DeleteObject(region)
    image.putalpha(mask)
    if envelope is None:return image
    canvas=Image.new('RGB',(envelope[2]-envelope[0],envelope[3]-envelope[1]),'#0A101A')
    if user.IsWindowVisible(hwnd):canvas.paste(image,(rect.left-envelope[0],rect.top-envelope[1]),image)
    return canvas
