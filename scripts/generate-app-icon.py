"""Render the existing launcher geometry into DPI-specific Windows icon frames."""
from pathlib import Path
from PIL import Image, ImageDraw

repo=Path(__file__).resolve().parents[1]
target=repo/'src/RemindAtDone/Assets/remind-at-done.ico';target.parent.mkdir(parents=True,exist_ok=True)
segments=[((10,1),(11,7),(13,9),(19,10)),((19,10),(13,11),(11,13),(10,19)),
          ((10,19),(9,13),(7,11),(1,10)),((1,10),(7,9),(9,7),(10,1))]
def frame(size):
    supersample=8;side=size*supersample;unit=side/48
    image=Image.new('RGBA',(side,side));gradient=Image.new('RGBA',(side,side));paint=ImageDraw.Draw(gradient)
    for y in range(side):
        fraction=y/(side-1);color=tuple(round(a+(b-a)*fraction) for a,b in zip((45,61,84),(19,29,44)))
        paint.line((0,y,side,y),fill=(*color,255))
    mask=Image.new('L',(side,side));ImageDraw.Draw(mask).ellipse((2*unit,2*unit,46*unit,46*unit),fill=255)
    image.paste(gradient,(0,0),mask);paint=ImageDraw.Draw(image)
    paint.ellipse((2*unit,2*unit,46*unit,46*unit),outline=(91,125,142,255),width=max(supersample,round(1.2*unit)))
    points=[]
    for curve in segments:
        for index in range(65):
            t=index/64;weights=((1-t)**3,3*(1-t)**2*t,3*(1-t)*t*t,t**3)
            x,y=(sum(weight*point[axis] for weight,point in zip(weights,curve)) for axis in (0,1))
            points.append(((24+(x-10)*1.283333)*unit,(24+(y-10)*1.283333)*unit))
    paint.line(points,fill=(160,235,203,255),width=max(supersample,round(1.65*unit)),joint='curve')
    return image.resize((size,size),Image.Resampling.LANCZOS)

sizes=[16,20,24,32,48,64,128,256];frames=[frame(size) for size in sizes]
frames[-1].save(target,format='ICO',sizes=[(size,size) for size in sizes],append_images=frames[:-1])
with Image.open(target) as icon:assert icon.ico.sizes()=={(size,size) for size in sizes}
preview=repo/'output/release_1029/tray-icon-preview.png';preview.parent.mkdir(parents=True,exist_ok=True)
sheet=Image.new('RGBA',(260,92),'#111925')
for x,size in zip((12,50,92,146,204),sizes[:5]):sheet.alpha_composite(frame(size),(x,(92-size)//2))
sheet.save(preview)
print(target)
