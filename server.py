import asyncio, json, math, random, secrets, time, os
from pathlib import Path
from aiohttp import web, WSMsgType
ROOT=Path(__file__).parent
COLORS=['#f04444','#3994f6','#27c96d','#ffcd3c','#af69ff','#ff78b5','#00d6d6','#f77e27','#c9e856','#7b9cff','#a64e3d','#ededed','#8bdebd','#e954a3','#c3a2ff','#adcf40','#f39a83','#3dcaac','#d1a44c','#6c7aff','#f262cd','#7dc8ff','#f0e07d','#ab8273','#7ad46e','#b6b6d7']
rooms={}
def within(x,y):return x*x+y*y<=48*48
def position(i):a=2*math.pi*i/26;return round(45*math.cos(a),2),round(45*math.sin(a),2)
def player(i,name,bot=False):
 x,y=position(i)
 return dict(id=i,name=name,color=COLORS[i],hat=i%5,x=x,y=y,alive=True,sword=False,immune=0,boost=0,slow=False,bot=bot,dx=0,dy=0,angle=random.random()*6.28,turn=0)
def spawn(r,kind):
 for _ in range(100):
  a=random.random()*math.tau;d=math.sqrt(random.random())*44;x=math.cos(a)*d;y=math.sin(a)*d
  if kind!='speed' and any(p['type']!='speed' and abs(p['x']-x)<36 and abs(p['y']-y)<36 for p in r['power']):continue
  r['power'].append(dict(id=secrets.token_hex(3),type=kind,x=x,y=y));return True
 return False
def paint(r,p,radius=2.8):
 x,y=p['x'],p['y']
 for yy in range(max(0,int(y-radius+50)),min(100,int(y+radius+51))):
  for xx in range(max(0,int(x-radius+50)),min(100,int(x+radius+51))):
   X=xx-49.5;Y=yy-49.5
   if within(X,Y) and (X-x)**2+(Y-y)**2<=radius**2:r['tiles'][yy*100+xx]=p['id']+1
def square(r,p,x,y):
 for yy in range(max(0,int(y)+42),min(100,int(y)+58)):
  for xx in range(max(0,int(x)+42),min(100,int(x)+58)):
   if within(xx-49.5,yy-49.5):r['tiles'][yy*100+xx]=p['id']+1
def room_public(r):
 return dict(code=r['code'],phase=r['phase'],remaining=max(0,round(r['ends']-time.monotonic(),1)) if r['phase']=='playing' else 60,players=[{k:v for k,v in p.items() if k not in ('dx','dy','angle','turn')} for p in r['players']],power=r['power'],tiles=r['tiles'],host=r['host'],ranking=r.get('ranking',[]))
async def broadcast(r):
 msg=json.dumps(dict(type='state',state=room_public(r)),separators=(',',':'))
 for ws in list(r['clients'].values()):
  if not ws.closed:
   try:await ws.send_str(msg)
   except Exception:pass
async def loop(r):
 last=time.monotonic();last_broadcast=0
 while r['phase']=='playing':
  now=time.monotonic();dt=min(.08,now-last);last=now
  for p in r['players']:
   if not p['alive']:continue
   if p['bot']:
    p['turn']-=dt
    if p['turn']<=0:p['angle']+=random.uniform(-2,2);p['turn']=random.uniform(.4,1.6)
    dx=math.cos(p['angle']);dy=math.sin(p['angle'])
   else:dx=p['dx'];dy=p['dy']
   mag=max(1,math.hypot(dx,dy));speed=(4 if p['slow'] else 10)*(1.8 if p['boost']>0 and not p['slow'] else 1)
   nx=p['x']+dx/mag*speed*dt;ny=p['y']+dy/mag*speed*dt
   if within(nx,ny):p['x']=nx;p['y']=ny
   elif p['bot']:p['angle']+=math.pi
   paint(r,p);p['boost']=max(0,p['boost']-dt);p['immune']=max(0,p['immune']-dt)
  for item in r['power'][:]:
   for p in r['players']:
    if p['alive'] and (p['x']-item['x'])**2+(p['y']-item['y'])**2<5.3:
     typ=item['type']
     if typ=='speed' and p['boost']<=0 and not p['slow']:p['boost']=5
     elif typ=='bomb':square(r,p,item['x'],item['y'])
     elif typ=='grapes':p['immune']=15.6
     elif typ=='sword':p['sword']=True
     elif typ=='world':
      for j in range(10000):
       x=j%100-49.5;y=j//100-49.5
       if within(x,y):r['tiles'][j]=p['id']+1
     elif typ=='eagle':
      for other in r['players']:
       if other!=p:other['alive']=False
      p['slow']=True;p['boost']=0
     r['power'].remove(item);break
  for a in r['players']:
   if not a['alive'] or not a['sword']:continue
   for b in r['players']:
    if a==b or not b['alive'] or b['sword'] or b['immune']>0:continue
    if (a['x']-b['x'])**2+(a['y']-b['y'])**2<4.5:
     b['alive']=False;a['sword']=False
     if a['boost']<=0 and not a['slow']:a['boost']=5
     break
  for typ,interval in [('speed',10),('bomb',7.5),('sword',5.5),('grapes',10)]:
   if now>=r['next'][typ]:
    spawn(r,typ);r['next'][typ]+=interval
  if now>=r['next']['world'] and not r['world_done']:
   r['world_done']=True
   if random.random()<.10:spawn(r,'world')
  if now>=r['next']['eagle'] and not r['eagle_done']:
   r['eagle_done']=True
   if random.random()<.01:spawn(r,'eagle')
  if now>=r['ends']:
   r['phase']='ended'
   total=sum(within(i%100-49.5,i//100-49.5) for i in range(10000))
   r['ranking']=sorted([dict(name=p['name'],color=p['color'],percent=round(100*r['tiles'].count(p['id']+1)/total,2),alive=p['alive']) for p in r['players']],key=lambda v:-v['percent'])
  if now-last_broadcast>.22 or r['phase']=='ended':await broadcast(r);last_broadcast=now
  await asyncio.sleep(.04)
async def home(req):return web.FileResponse(ROOT/'index.html')
async def socket(req):
 ws=web.WebSocketResponse(heartbeat=20);await ws.prepare(req)
 room=None;pid=None
 try:
  async for msg in ws:
   if msg.type!=WSMsgType.TEXT:continue
   try:m=json.loads(msg.data)
   except Exception:continue
   act=m.get('action')
   if act in ('create','join') and room is None:
    if act=='create':
     code=''.join(str(random.randrange(10)) for _ in range(6))
     while code in rooms:code=''.join(str(random.randrange(10)) for _ in range(6))
     room=dict(code=code,host=0,phase='lobby',players=[player(i,'Bot '+str(i+1),True) for i in range(26)],clients={},tiles=[0]*10000,power=[],ends=0)
     rooms[code]=room;pid=0
    else:
     room=rooms.get(str(m.get('code','')).strip())
     if not room or room['phase']!='lobby' or 1 in room['clients']:
      await ws.send_json(dict(type='error',message='Sala no disponible o segundo espacio ocupado'));room=None;continue
     pid=1
    p=room['players'][pid];p['bot']=False;p['name']=str(m.get('name','Jugador'))[:16] or 'Jugador';room['clients'][pid]=ws
    await ws.send_json(dict(type='welcome',id=pid,code=room['code'],host=pid==0))
    await broadcast(room)
   elif room is not None:
    if act=='customize' and room['phase']=='lobby':
     color=m.get('color');hat=m.get('hat')
     if isinstance(color,int) and 0<=color<26 and color!=pid:
      # Exchange color slots with bot, preserving fixed player IDs
      other=room['players'][color]
      if other['bot']:
       room['players'][pid]['color'],other['color']=other['color'],room['players'][pid]['color']
     if isinstance(hat,int) and 0<=hat<=4:room['players'][pid]['hat']=hat
     await broadcast(room)
    elif act=='start' and pid==0 and room['phase']=='lobby':
     room['phase']='playing';room['ends']=time.monotonic()+60
     room['next']={k:time.monotonic()+v for k,v in [('speed',10),('bomb',7.5),('sword',5.5),('grapes',10),('world',18),('eagle',24)]}
     room['world_done']=room['eagle_done']=False
     asyncio.create_task(loop(room));await broadcast(room)
    elif act=='move' and room['phase']=='playing' and room['players'][pid]['alive']:
     try:
      x=float(m.get('x',0));y=float(m.get('y',0))
      room['players'][pid]['dx']=max(-1,min(1,x)) if math.isfinite(x) else 0
      room['players'][pid]['dy']=max(-1,min(1,y)) if math.isfinite(y) else 0
     except Exception:pass
 finally:
  if room is not None and pid is not None:
   room['clients'].pop(pid,None)
   if room['phase']=='lobby':
    room['players'][pid]['bot']=True;room['players'][pid]['name']='Bot '+str(pid+1)
    if not room['clients']:rooms.pop(room['code'],None)
    else:await broadcast(room)
 return ws
app=web.Application();app.router.add_get('/',home);app.router.add_get('/ws',socket)
if __name__=='__main__':web.run_app(app,host='0.0.0.0',port=int(os.environ.get('PORT',8080)))
