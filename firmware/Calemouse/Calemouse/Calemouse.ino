#include <HijelHID_BLEMouse.h>
#include <Wire.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <ESPmDNS.h>

// Wi-Fi: primero intenta la red normal; si no conecta en WIFI_TIMEOUT_MS, crea su
// propia red "Calestick-AP". Pon tu red en wifi_secrets.h (no se sube a git):
//   #define WIFI_SSID "MiRed"
//   #define WIFI_PASS "MiClave"
#if __has_include("wifi_secrets.h")
#include "wifi_secrets.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
const unsigned long WIFI_TIMEOUT_MS = 10000;
const char *HOSTNAME = "calestick";     // http://calestick.local en cualquiera de las dos redes

const int SDA_PIN = 8;
const int SCL_PIN = 9;
const uint8_t MPU = 0x68;

// point = true: modo apuntar. El cursor se mueve lo mismo que gira la cabeza
// (gain px por grado): girar = izquierda/derecha, asentir = arriba/abajo.
// point = false: modo joystick, la inclinación decide la velocidad (dead/range/speed/expo).
struct Cfg {
    float dead = 6, range = 35, speed = 20, expo = 1.8f, smooth = 0.5f, fuse = 0.98f;
    bool invX = true, invY = false, swap = false, on = true;
    float gain = 40, still = 1.5f;
    bool point = true;
};
Cfg cfg;
Preferences prefs;

HijelBLEMouse bleMouse("Calestick", "ZeepLab", 72);
WebServer server(80);

float accX = 0, accY = 0, vx = 0, vy = 0;
float roll = 0, pitch = 0, yaw = 0, zr = 0, zp = 0, tr = 0, tp = 0, sr = 0, sp = 0;
float gbx = 0, gby = 0, gbz = 0;
float minR = 0, maxR = 0, minP = 0, maxP = 0;
float lax = 0, lay = 0, laz = 1, lgx = 0, lgy = 0, lgz = 0, ltemp = 0;
float fyaw = 0, fpit = 0, dYaw = 0, dPit = 0;   // modo apuntar: giro filtrado y grados pendientes
unsigned long tPrev = 0, tMove = 0;
const unsigned long MOVE_MS = 10;       // un reporte BLE cada 10 ms; lo que sobra se acumula
// Deriva del giróscopo (sobre todo en yaw, que no tiene la gravedad como referencia):
// el sesgo cambia mientras el chip se calienta. Si la cabeza está quieta STILL_S seguidos
// (giro filtrado < STILL_DPS), el sesgo se reaprende rápido y el cursor queda en cero exacto.
const float STILL_DPS = 1.0f;
const float STILL_S = 0.3f;
const float BIAS_TAU_S = 0.2f;          // qué tan rápido se reaprende el sesgo estando quieto
float gmag = 0, stillFor = 0;           // giro filtrado (°/s) y segundos quieto
bool still = false;
float yawRate = 0;                      // giro de voltear (°/s), lo usa la sacudida

// Recalibrar sacudiendo la cabeza (sin entrar a la página): SHAKE_TURNS cambios de sentido
// a más de SHAKE_DPS dentro de SHAKE_WINDOW_S. Luego el cursor se congela, se espera a que
// la cabeza quede quieta SETTLE_S y se calibra como el botón "Calibrar giro" (y recentra).
// EyeClick no recibe datos del ESP32, así que se le avisa con el propio cursor: al empezar
// baja SIGNAL_PX y vuelve EXACTO; al terminar va a la derecha y vuelve. EyeClick reconoce
// esos dos "parpadeos" del cursor y muestra "Calibrating gyro". Si la placa tiene LED RGB:
// amarillo calibrando, verde listo.
const float SHAKE_DPS = 90.0f;
const int SHAKE_TURNS = 8;
const float SHAKE_WINDOW_S = 3.0f;
const float SETTLE_DPS = 6.0f;          // "quieto" tras sacudir: más flojo que STILL_DPS
const float SETTLE_S = 0.6f;
const float SETTLE_TIMEOUT_S = 8.0f;
const int SIGNAL_PX = 40;
bool settling = false;                  // sacudida detectada: cursor congelado, esperando quietud
int shakeSign = 0, nTurns = 0;
unsigned long turns[SHAKE_TURNS];
unsigned long settleStart = 0, movingAt = 0;
bool wifiPending = false;               // intentando conectar a la red normal
unsigned long wifiStart = 0;

const char PAGE[] PROGMEM = R"=====(<!DOCTYPE html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Calestick</title>
<style>
:root{--b:rgba(255,255,255,.3);--t:#f4f7ff}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;color:var(--t);font:15px/1.4 -apple-system,system-ui,"Segoe UI",sans-serif;background:#0b1020}
.bg{position:fixed;inset:0;z-index:-1;overflow:hidden;background:linear-gradient(135deg,#0b1030,#1a0f3a 50%,#06223a)}
.bg i{position:absolute;border-radius:50%;filter:blur(60px);opacity:.75;animation:f 18s ease-in-out infinite alternate}
.bg i:nth-child(1){width:46vmax;height:46vmax;left:-10vmax;top:-8vmax;background:#3a6bff}
.bg i:nth-child(2){width:40vmax;height:40vmax;right:-12vmax;top:10vmax;background:#c13bff;animation-delay:-6s}
.bg i:nth-child(3){width:36vmax;height:36vmax;left:20vmax;bottom:-14vmax;background:#00d4c8;animation-delay:-11s}
@keyframes f{to{transform:translate(8vmax,6vmax) scale(1.15)}}
.wrap{max-width:1000px;margin:0 auto;padding:18px 16px 40px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
h1{margin:0;font-size:28px;letter-spacing:.5px}
h2{margin:0 0 10px;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;opacity:.75}
.chip{padding:6px 14px;border-radius:20px;font-size:13px;border:1px solid var(--b);background:rgba(255,255,255,.12);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.chip.ok{background:rgba(70,210,140,.35)}
.grid{display:grid;gap:16px;grid-template-columns:1fr}
@media(min-width:800px){.grid{grid-template-columns:1fr 1fr}}
.wide{grid-column:1/-1}
.glass{position:relative;padding:18px;border-radius:28px;border:1px solid var(--b);
background:linear-gradient(145deg,rgba(255,255,255,.22),rgba(255,255,255,.06));
backdrop-filter:blur(22px) saturate(180%);-webkit-backdrop-filter:blur(22px) saturate(180%);
box-shadow:0 12px 40px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.55),inset 0 -1px 0 rgba(255,255,255,.1)}
.glass::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;
background:radial-gradient(120% 55% at 20% 0%,rgba(255,255,255,.3),transparent 55%)}
#cv{display:block;width:100%;height:380px;border-radius:20px;touch-action:none;cursor:grab;
border:1px solid rgba(255,255,255,.15);background:radial-gradient(90% 80% at 50% 35%,rgba(255,255,255,.1),rgba(0,0,0,.2))}
#cv:active{cursor:grabbing}
.hint{font-size:12px;opacity:.65;margin:8px 0 12px;text-align:center}
.ro{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px}
.ro>div{flex:1 1 110px;text-align:center;padding:8px;border-radius:16px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);border-top:3px solid rgba(255,255,255,.3)}
.ro .x{border-top-color:#ff5a6a}.ro .y{border-top-color:#4ee38a}.ro .z{border-top-color:#5aa8ff}.ro .t{border-top-color:#ffd54a}
.ro small{display:block;font-size:11px;letter-spacing:1px;opacity:.7}
.ro b{font-size:24px;font-variant-numeric:tabular-nums}
.ro em{display:block;font-size:11px;font-style:normal;opacity:.65}
.dat{display:grid;grid-template-columns:auto 1fr 1fr 1fr;gap:8px 12px;align-items:center;font-variant-numeric:tabular-nums;font-size:15px;margin-bottom:8px}
.dat b{text-align:center}.dat span:not(:first-child){text-align:center}
.cx{color:#ff5a6a}.cy{color:#4ee38a}.cz{color:#5aa8ff}
.lvl{position:relative;width:200px;height:200px;margin:8px auto 12px;border-radius:50%;background:rgba(255,255,255,.07);border:1px solid var(--b);box-shadow:inset 0 0 30px rgba(255,255,255,.14)}
.lvl s{position:absolute;inset:0;background:linear-gradient(var(--b),var(--b)) center/1px 100% no-repeat,linear-gradient(var(--b),var(--b)) center/100% 1px no-repeat}
.lvl u{position:absolute;left:50%;top:50%;border-radius:50%;transform:translate(-50%,-50%);text-decoration:none}
#rg{border:1px dashed rgba(124,196,255,.8)}
#dz{border:1px solid rgba(255,120,140,.85);background:rgba(255,100,120,.14)}
#dot{position:absolute;left:50%;top:50%;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;
background:radial-gradient(circle at 30% 25%,#fff,rgba(255,255,255,.6) 45%,rgba(140,200,255,.6));border:1px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.45)}
.row{margin:10px 0}
.lb{display:flex;justify-content:space-between;margin-bottom:6px;font-size:14px}
.lb b{font-variant-numeric:tabular-nums}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:8px;border-radius:8px;background:rgba(255,255,255,.2);box-shadow:inset 0 1px 2px rgba(0,0,0,.35);outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:26px;height:26px;border-radius:50%;
background:radial-gradient(circle at 30% 25%,#fff,rgba(255,255,255,.55) 45%,rgba(180,220,255,.45));border:1px solid rgba(255,255,255,.85);box-shadow:0 3px 10px rgba(0,0,0,.4),inset 0 -3px 6px rgba(120,180,255,.5)}
input[type=range]::-moz-range-thumb{width:24px;height:24px;border-radius:50%;background:#e8f2ff;border:1px solid #fff}
.tg{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.sw{display:flex;align-items:center;gap:10px;cursor:pointer;font-size:14px}
.sw input{display:none}
.sw span{flex:none;width:48px;height:28px;border-radius:20px;background:rgba(255,255,255,.18);border:1px solid var(--b);position:relative;transition:.2s}
.sw span::after{content:"";position:absolute;top:2px;left:2px;width:22px;height:22px;border-radius:50%;background:radial-gradient(circle at 30% 25%,#fff,#cfe4ff);box-shadow:0 2px 6px rgba(0,0,0,.4);transition:.2s}
.sw input:checked+span{background:rgba(80,210,140,.6)}
.sw input:checked+span::after{left:22px}
.btns{display:flex;flex-wrap:wrap;gap:10px}
.btn{padding:11px 16px;border-radius:16px;border:1px solid var(--b);color:var(--t);font:inherit;font-weight:600;cursor:pointer;
background:linear-gradient(145deg,rgba(255,255,255,.32),rgba(255,255,255,.08));box-shadow:inset 0 1px 0 rgba(255,255,255,.5);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.btn:active{transform:scale(.97)}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(80px);padding:10px 20px;border-radius:20px;border:1px solid var(--b);
background:rgba(255,255,255,.2);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);transition:.3s}
#toast.s{transform:translateX(-50%) translateY(0)}
</style></head><body>
<div class=bg><i></i><i></i><i></i></div>
<div class=wrap>
<header><h1>Calestick</h1><span id=ble class=chip>--</span></header>
<div class=grid>

<section class="glass wide">
<h2>Orientaci&oacute;n 3D</h2>
<canvas id=cv></canvas>
<div class=hint>Arrastra para girar la vista &middot; <span class=cx>X</span> <span class=cy>Y</span> <span class=cz>Z</span> son los ejes del sensor</div>
<div class=ro>
<div class=x><small>ROLL &middot; EJE X</small><b id=eR>0.0&deg;</b><em id=eRr></em></div>
<div class=y><small>PITCH &middot; EJE Y</small><b id=eP>0.0&deg;</b><em id=ePr></em></div>
<div class=z><small>YAW &middot; EJE Z</small><b id=eY>0.0&deg;</b><em>deriva con el tiempo</em></div>
<div class=t><small>INCLINACI&Oacute;N TOTAL</small><b id=eT>0.0&deg;</b><em>respecto a la vertical</em></div>
</div>
<div class=tg>
<label class=sw><input type=checkbox id=Laxes checked><span></span>Ejes del sensor</label>
<label class=sw><input type=checkbox id=Lworld checked><span></span>Ejes del mundo</label>
<label class=sw><input type=checkbox id=Lrings checked><span></span>Anillos de rotaci&oacute;n</label>
<label class=sw><input type=checkbox id=Lgrid checked><span></span>Rejilla</label>
<label class=sw><input type=checkbox id=Lgrav checked><span></span>Vector de gravedad</label>
<label class=sw><input type=checkbox id=i3r><span></span>Invertir roll 3D</label>
<label class=sw><input type=checkbox id=i3p><span></span>Invertir pitch 3D</label>
<label class=sw><input type=checkbox id=i3y><span></span>Invertir yaw 3D</label>
</div>
<div class=btns><button class=btn onclick="vreset()">Vista inicial</button></div>
</section>

<section class=glass>
<h2>Nivel y zonas</h2>
<div class=lvl><u id=rg></u><u id=dz></u><s></s><i id=dot></i></div>
<div class=ro>
<div><small>VEL X</small><b id=vx>0</b></div>
<div><small>VEL Y</small><b id=vy>0</b></div>
</div>
<div style="font-size:12px;opacity:.7;margin-top:10px;text-align:center">Rojo: zona muerta &middot; Azul: rango hasta velocidad m&aacute;xima (escala 45&deg;)</div>
</section>

<section class=glass>
<h2>Datos del sensor</h2>
<div class=dat>
<span></span><b class=cx>X</b><b class=cy>Y</b><b class=cz>Z</b>
<span>Acel (g)</span><span id=ax>0</span><span id=ay>0</span><span id=az>0</span>
<span>Giro (&deg;/s)</span><span id=gx>0</span><span id=gy>0</span><span id=gz>0</span>
</div>
<div class=ro>
<div><small>TEMPERATURA</small><b id=tc>--</b></div>
<div><small>|ACEL|</small><b id=an>--</b></div>
</div>
</section>

<section class="glass wide">
<h2>Ajustes</h2>
<div id=sl></div>
<div class=tg id=tg></div>
<div class=btns>
<button class=btn onclick="act('zero','Recentrado')">Recentrar</button>
<button class=btn id=bc onclick="calib()">Calibrar giro</button>
<button class=btn onclick="act('reset','Rango reiniciado')">Reiniciar rango</button>
<button class=btn onclick="act('save','Guardado')">Guardar</button>
<button class=btn onclick="defs()">Valores de f&aacute;brica</button>
</div>
</section>

</div></div>
<div id=toast></div>
<script>
(()=>{
const $=i=>document.getElementById(i);
const S=[['gain','Sensibilidad (apuntar)','px/&deg;',5,150,1],['still','Filtro de temblor (apuntar)','&deg;/s',0,5,.1],['dead','Zona muerta (joystick)','&deg;',0,20,.5],['range','Rango hasta velocidad m&aacute;xima (joystick)','&deg;',5,60,1],['speed','Velocidad m&aacute;xima (joystick)','px',1,60,1],['expo','Curva (joystick)','',1,3,.1],['smooth','Suavizado','',0,.95,.01],['fuse','Filtro del giroscopio','',.9,.999,.001]];
const T=[['on','Mouse activo'],['point','Modo apuntar (girar la cabeza)'],['invX','Invertir X'],['invY','Invertir Y'],['swap','Intercambiar ejes']];
const LV=45,D2R=Math.PI/180,TAU=Math.PI*2;
let C={};const tm={};
function fmt(k,v){const d=k=='fuse'?3:(k=='smooth'||k=='expo')?2:k=='gain'?0:1;return (+v).toFixed(d)}
function send(k,v){clearTimeout(tm[k]);tm[k]=setTimeout(()=>fetch('/set?k='+k+'&v='+v).catch(()=>{}),40)}
function toast(t){const e=$('toast');e.textContent=t;e.classList.add('s');setTimeout(()=>e.classList.remove('s'),1600)}
function lvRings(){
const dz=2*C.dead/LV*100,rg=Math.min(200,2*(C.dead+C.range)/LV*100);
$('dz').style.width=$('dz').style.height=dz+'px';
$('rg').style.width=$('rg').style.height=rg+'px'}
function build(){
const sl=$('sl');sl.innerHTML='';
S.forEach(([k,n,u,mn,mx,st])=>{
const d=document.createElement('div');d.className='row';
d.innerHTML='<div class=lb><span>'+n+'</span><b></b></div><input type=range min='+mn+' max='+mx+' step='+st+'>';
sl.appendChild(d);
const i=d.querySelector('input'),b=d.querySelector('b');
i.value=C[k];b.innerHTML=fmt(k,C[k])+u;
i.oninput=()=>{b.innerHTML=fmt(k,i.value)+u;C[k]=+i.value;send(k,i.value);lvRings()}});
const tg=$('tg');tg.innerHTML='';
T.forEach(([k,n])=>{
const l=document.createElement('label');l.className='sw';
l.innerHTML='<input type=checkbox><span></span>'+n;
const c=l.querySelector('input');c.checked=!!C[k];
c.onchange=()=>send(k,c.checked?1:0);
tg.appendChild(l)});
lvRings()}
async function load(){C=await(await fetch('/cfg')).json();build()}
async function act(p,m){await fetch('/'+p);toast(m)}
async function calib(){const b=$('bc');b.disabled=true;b.textContent='Quieto...';await fetch('/calib');b.disabled=false;b.textContent='Calibrar giro';toast('Giro calibrado')}
async function defs(){await fetch('/defaults');await load();toast('Valores de f\u00e1brica')}

const cv=$('cv'),ctx=cv.getContext('2d');
let VW=300,VH=300,DPR=1,SC=50;const PD=9;
function fit(){DPR=window.devicePixelRatio||1;VW=cv.clientWidth||300;VH=cv.clientHeight||300;
cv.width=Math.round(VW*DPR);cv.height=Math.round(VH*DPR);SC=Math.min(VW/7.5,VH/6.2)}
new ResizeObserver(fit).observe(cv);fit();

let az=-35*D2R,el=24*D2R,drag=null;
cv.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,az:az,el:el};cv.setPointerCapture(e.pointerId)};
cv.onpointermove=e=>{if(!drag)return;az=drag.az+(e.clientX-drag.x)*.01;el=Math.max(-1.45,Math.min(1.45,drag.el+(e.clientY-drag.y)*.01))};
cv.onpointerup=cv.onpointercancel=()=>{drag=null};
function vreset(){az=-35*D2R;el=24*D2R}

function rx(a){const c=Math.cos(a),s=Math.sin(a);return[1,0,0,0,c,-s,0,s,c]}
function ry(a){const c=Math.cos(a),s=Math.sin(a);return[c,0,s,0,1,0,-s,0,c]}
function rz(a){const c=Math.cos(a),s=Math.sin(a);return[c,-s,0,s,c,0,0,0,1]}
function mm(a,b){const o=[];for(let i=0;i<3;i++)for(let j=0;j<3;j++)o.push(a[i*3]*b[j]+a[i*3+1]*b[3+j]+a[i*3+2]*b[6+j]);return o}
function mv(m,v){return[m[0]*v[0]+m[1]*v[1]+m[2]*v[2],m[3]*v[0]+m[4]*v[1]+m[5]*v[2],m[6]*v[0]+m[7]*v[1]+m[8]*v[2]]}
let V=null,B=null;
function pj(v){const w=mv(V,v),k=PD/(PD+w[1]);return[VW/2+w[0]*SC*k,VH*.53-w[2]*SC*k,w[1]]}
function pb(v){return pj(mv(B,v))}
function ln(a,b,col,w,dash){ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.strokeStyle=col;ctx.lineWidth=w||1;ctx.setLineDash(dash||[]);ctx.stroke();ctx.setLineDash([])}
function arr(a,b,col,w,dash){ln(a,b,col,w,dash);const dx=b[0]-a[0],dy=b[1]-a[1],l=Math.hypot(dx,dy)||1,ux=dx/l,uy=dy/l,h=10;
ctx.beginPath();ctx.moveTo(b[0],b[1]);ctx.lineTo(b[0]-ux*h-uy*h*.5,b[1]-uy*h+ux*h*.5);ctx.lineTo(b[0]-ux*h+uy*h*.5,b[1]-uy*h-ux*h*.5);ctx.closePath();ctx.fillStyle=col;ctx.fill()}
function txt(s,p,col,dx,dy){ctx.font='600 13px system-ui,sans-serif';ctx.fillStyle=col;ctx.fillText(s,p[0]+dx,p[1]+dy)}
function dotp(p,r,col){ctx.beginPath();ctx.arc(p[0],p[1],r,0,TAU);ctx.fillStyle=col;ctx.fill()}
function ring3(ax,R,col,ang){
const f=ax=='x'?t=>[0,R*Math.cos(t),R*Math.sin(t)]:ax=='y'?t=>[R*Math.sin(t),0,R*Math.cos(t)]:t=>[R*Math.cos(t),R*Math.sin(t),0];
ctx.beginPath();
for(let i=0;i<=72;i++){const q=pj(f(i/72*TAU));if(i)ctx.lineTo(q[0],q[1]);else ctx.moveTo(q[0],q[1])}
ctx.strokeStyle=col+'44';ctx.lineWidth=1.2;ctx.stroke();
const n=Math.max(2,Math.ceil(Math.abs(ang)/.08));
ctx.beginPath();
for(let i=0;i<=n;i++){const q=pj(f(ang*i/n));if(i)ctx.lineTo(q[0],q[1]);else ctx.moveTo(q[0],q[1])}
ctx.strokeStyle=col;ctx.lineWidth=4;ctx.lineCap='round';ctx.stroke();ctx.lineCap='butt';
dotp(pj(f(0)),2.5,'#ffffff');
const e=pj(f(ang));dotp(e,5,col);
txt((ang/D2R).toFixed(0)+'\u00b0',e,col,8,-8)}

const HX=1.1,HY=.7,HZ=.14;
const VT=[];for(const a of[-1,1])for(const b of[-1,1])for(const c of[-1,1])VT.push([a*HX,b*HY,c*HZ]);
const FC=[
{i:[1,3,7,5],n:[0,0,1],c:[110,225,210]},
{i:[0,4,6,2],n:[0,0,-1],c:[70,110,200]},
{i:[4,5,7,6],n:[1,0,0],c:[255,120,140]},
{i:[0,2,3,1],n:[-1,0,0],c:[110,150,230]},
{i:[2,6,7,3],n:[0,1,0],c:[110,235,160]},
{i:[0,1,5,4],n:[0,-1,0],c:[110,150,230]}];
const LX=-.395,LY=-.543,LZ=.741;
const tgt={r:0,p:0,y:0},cur={r:0,p:0,y:0};
let acc=[0,0,1];

function poly(pts){ctx.beginPath();pts.forEach((q,i)=>{if(i)ctx.lineTo(q[0],q[1]);else ctx.moveTo(q[0],q[1])});ctx.closePath()}

function draw(){
requestAnimationFrame(draw);
ctx.setTransform(DPR,0,0,DPR,0,0);ctx.clearRect(0,0,VW,VH);
const kr=$('i3r').checked?-1:1,kp=$('i3p').checked?-1:1,ky=$('i3y').checked?-1:1;
cur.r+=(tgt.r-cur.r)*.3;cur.p+=(tgt.p-cur.p)*.3;
let dy=tgt.y-cur.y;dy=((dy+540)%360)-180;cur.y+=dy*.3;
const r=cur.r*kr*D2R,p=cur.p*kp*D2R,y=cur.y*ky*D2R;
V=mm(rx(el),rz(az));
B=mm(rz(y),mm(ry(p),rx(r)));

if($('Lgrid').checked){
for(let i=-3;i<=3;i++){
ln(pj([i,-3,-1.5]),pj([i,3,-1.5]),'rgba(255,255,255,.14)',1);
ln(pj([-3,i,-1.5]),pj([3,i,-1.5]),'rgba(255,255,255,.14)',1)}}

if($('Lworld').checked){
const o0=pj([0,0,0]);
[['X',[2.7,0,0]],['Y',[0,2.7,0]],['Z',[0,0,2.7]]].forEach(([n,v])=>{
const e=pj(v);ln(o0,e,'rgba(255,255,255,.35)',1,[5,5]);txt(n.toLowerCase(),e,'rgba(255,255,255,.55)',6,-4)})}

if($('Lrings').checked){
ring3('x',1.9,'#ff5a6a',r);
ring3('y',2.15,'#4ee38a',p);
ring3('z',2.4,'#5aa8ff',y)}

const fs=FC.map(f=>{
const pts=f.i.map(i=>pb(VT[i]));
const d=(pts[0][2]+pts[1][2]+pts[2][2]+pts[3][2])/4;
const nv=mv(V,mv(B,f.n));
const sh=.5+.5*Math.max(0,nv[0]*LX+nv[1]*LY+nv[2]*LZ);
return{f:f,pts:pts,d:d,sh:sh}}).sort((a,b)=>b.d-a.d);
fs.forEach(o=>{
poly(o.pts);
const c=o.f.c.map(v=>Math.round(v*o.sh));
ctx.fillStyle='rgba('+c.join(',')+',.46)';ctx.fill();
ctx.strokeStyle='rgba(255,255,255,.75)';ctx.lineWidth=1.6;ctx.lineJoin='round';ctx.stroke();
if(o.f===FC[0]){
const z=HZ+.004;
const chip=[[-.9,-.5,z],[-.45,-.5,z],[-.45,-.1,z],[-.9,-.1,z]].map(pb);
poly(chip);ctx.fillStyle='rgba(10,20,40,.75)';ctx.fill();ctx.strokeStyle='rgba(255,255,255,.5)';ctx.lineWidth=1;ctx.stroke();
dotp(pb([-.82,-.42,z]),2.5,'#ffffff')}});

const o=pb([0,0,0]);
if($('Laxes').checked){
[['X',[1.9,0,0],[-1.3,0,0],'#ff5a6a'],['Y',[0,1.45,0],[0,-1,0],'#4ee38a'],['Z',[0,0,1.2],[0,0,-.8],'#5aa8ff']].forEach(([n,v,w,c])=>{
ln(o,pb(w),c+'66',2);
const e=pb(v);arr(o,e,c,3);txt(n,e,c,8,-6)})}
if($('Lgrav').checked){
const an=Math.hypot(acc[0],acc[1],acc[2])||1;
const g=pb([acc[0]/an*1.7,acc[1]/an*1.7,acc[2]/an*1.7]);
arr(o,g,'#ffd54a',2.5,[6,4]);txt('g',g,'#ffd54a',8,-6)}
dotp(o,4,'#ffffff')}

async function tick(){
try{
const d=await(await fetch('/d')).json();
tgt.r=d.r;tgt.p=d.p;tgt.y=d.y;acc=[d.ax,d.ay,d.az];
$('eR').innerHTML=d.r.toFixed(1)+'&deg;';
$('eP').innerHTML=d.p.toFixed(1)+'&deg;';
$('eY').innerHTML=d.y.toFixed(1)+'&deg;';
$('eRr').textContent='rango '+d.rmin.toFixed(0)+' a '+d.rmax.toFixed(0);
$('ePr').textContent='rango '+d.pmin.toFixed(0)+' a '+d.pmax.toFixed(0);
const an=Math.hypot(d.ax,d.ay,d.az)||1;
const tilt=Math.acos(Math.max(-1,Math.min(1,d.az/an)))/D2R;
$('eT').innerHTML=tilt.toFixed(1)+'&deg;';
$('ax').textContent=d.ax.toFixed(2);$('ay').textContent=d.ay.toFixed(2);$('az').textContent=d.az.toFixed(2);
$('gx').textContent=d.gx.toFixed(1);$('gy').textContent=d.gy.toFixed(1);$('gz').textContent=d.gz.toFixed(1);
$('tc').innerHTML=d.t.toFixed(1)+'&deg;C';$('an').textContent=an.toFixed(2)+' g';
$('vx').textContent=d.vx.toFixed(1);$('vy').textContent=d.vy.toFixed(1);
let x=d.r/LV*100,yy=d.p/LV*100;const m=Math.hypot(x,yy);if(m>100){x*=100/m;yy*=100/m}
$('dot').style.transform='translate('+x+'px,'+yy+'px)';
const b=$('ble');b.textContent=d.ble?'BLE conectado':'BLE esperando';b.className='chip'+(d.ble?' ok':'')}
catch(e){$('ble').textContent='Sin conexion';$('ble').className='chip'}
setTimeout(tick,70)}

window.act=act;window.calib=calib;window.defs=defs;window.vreset=vreset;
draw();
load().then(tick);
})();
</script></body></html>)=====";

void startAP() {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Calestick-AP", "12345678");
    MDNS.begin(HOSTNAME);
    Serial.print("Red propia Calestick-AP: http://");
    Serial.println(WiFi.softAPIP());
}

// No bloquea: arranca la conexión y loop() revisa con checkWifi(), así el mouse se mueve
// desde el primer momento aunque la red tarde o no exista.
void startWifi() {
    if (strlen(WIFI_SSID) == 0) {
        startAP();
        return;
    }
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(HOSTNAME);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    wifiPending = true;
    wifiStart = millis();
    Serial.printf("Conectando a %s...\n", WIFI_SSID);
}

void checkWifi() {
    if (!wifiPending) return;
    if (WiFi.status() == WL_CONNECTED) {
        wifiPending = false;
        MDNS.begin(HOSTNAME);
        Serial.print("Conectado a la red: http://");
        Serial.println(WiFi.localIP());
    } else if (millis() - wifiStart > WIFI_TIMEOUT_MS) {
        wifiPending = false;
        Serial.println("No se pudo conectar; usando red propia");
        startAP();
    }
}

void loadCfg() {
    if (prefs.getBytesLength("cfg3") == sizeof(Cfg)) prefs.getBytes("cfg3", &cfg, sizeof(Cfg));
}

void saveCfg() {
    prefs.putBytes("cfg3", &cfg, sizeof(Cfg));
}

void setKey(const String &k, float v) {
    if (k == "dead") cfg.dead = constrain(v, 0.0f, 30.0f);
    else if (k == "range") cfg.range = constrain(v, 1.0f, 90.0f);
    else if (k == "speed") cfg.speed = constrain(v, 0.0f, 100.0f);
    else if (k == "expo") cfg.expo = constrain(v, 0.5f, 4.0f);
    else if (k == "smooth") cfg.smooth = constrain(v, 0.0f, 0.98f);
    else if (k == "fuse") cfg.fuse = constrain(v, 0.8f, 0.9999f);
    else if (k == "invX") cfg.invX = v != 0;
    else if (k == "invY") cfg.invY = v != 0;
    else if (k == "swap") cfg.swap = v != 0;
    else if (k == "on") cfg.on = v != 0;
    else if (k == "gain") cfg.gain = constrain(v, 1.0f, 300.0f);
    else if (k == "still") cfg.still = constrain(v, 0.0f, 10.0f);
    else if (k == "point") cfg.point = v != 0;
}

void writeReg(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(MPU);
    Wire.write(reg);
    Wire.write(val);
    Wire.endTransmission();
}

bool readMPU(int16_t *v) {
    Wire.beginTransmission(MPU);
    Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(MPU, (uint8_t)14) != 14) return false;
    for (int i = 0; i < 7; i++) {
        int hi = Wire.read();
        int lo = Wire.read();
        v[i] = (int16_t)((hi << 8) | lo);
    }
    return true;
}

// Montaje del sensor (MPU-9265/9250/6500): placa PARADA sobre la patilla, la cara del chip
// (eje Z) mira hacia la IZQUIERDA del usuario. Qué lado de la placa queda arriba (X, Y o
// entre los dos) se mide con la gravedad al calibrar, así da igual hacia dónde queden los pines.
//   pitch = asentir (mirar arriba/abajo), giro alrededor de Z: giróscopo gz.
//   yaw   = voltear a los lados, giro alrededor de la vertical: giróscopo proyectado en la gravedad.
//   roll  = inclinar la cabeza hacia un hombro, giro alrededor del eje adelante/atrás
//           (en el plano de la placa, perpendicular a la vertical): gy*ux - gx*uy.
float ux = 0, uy = 1;               // vertical en el plano X-Y de la placa (unitario), al calibrar
float phi0 = 90;                    // ángulo de la gravedad en el plano X-Y al calibrar
float gux = 0, guy = 1, guz = 0;    // gravedad filtrada (unitaria) para el yaw

float wrap180(float a) {
    while (a > 180) a -= 360;
    while (a < -180) a += 360;
    return a;
}

// Ángulos medidos relativos a la postura de calibración, así ningún atan2 pasa por ±180°.
void accAngles(int16_t *v, float &r, float &p) {
    float ax = v[0], ay = v[1], az = v[2];
    p = -wrap180(atan2(ay, ax) * 57.2958f - phi0);
    r = atan2(az, ax * ux + ay * uy) * 57.2958f;
}

void calibrate() {
    int16_t v[7];
    float sgx = 0, sgy = 0, sgz = 0, sax = 0, say = 0, saz = 0;
    int n = 0;
    for (int i = 0; i < 200; i++) {
        if (readMPU(v)) {
            sax += v[0];
            say += v[1];
            saz += v[2];
            sgx += v[4];
            sgy += v[5];
            sgz += v[6];
            n++;
        }
        delay(5);
    }
    if (n == 0) return;
    gbx = sgx / n / 65.5f;
    gby = sgy / n / 65.5f;
    gbz = sgz / n / 65.5f;
    float ax = sax / n, ay = say / n, az = saz / n;
    float inPlane = sqrt(ax * ax + ay * ay), g = sqrt(ax * ax + ay * ay + az * az);
    if (inPlane > 1000) {               // si no, la placa está acostada: se dejan los valores previos
        ux = ax / inPlane;
        uy = ay / inPlane;
        phi0 = atan2(ay, ax) * 57.2958f;
    }
    if (g > 1000) {
        gux = ax / g;
        guy = ay / g;
        guz = az / g;
    }
    Serial.printf("Vertical en la placa: x=%.2f y=%.2f\n", ux, uy);
    roll = atan2(az, ax * ux + ay * uy) * 57.2958f;
    pitch = 0;
    yaw = 0;
    zr = roll;
    zp = pitch;
    tr = tp = sr = sp = 0;
    fyaw = fpit = dYaw = dPit = 0;
    minR = maxR = minP = maxP = 0;
    tPrev = micros();
}

void updateTilt() {
    int16_t v[7];
    if (!readMPU(v)) return;
    unsigned long now = micros();
    float dt = (now - tPrev) / 1000000.0f;
    tPrev = now;
    if (dt <= 0 || dt > 0.5f) return;
    float ar, ap;
    accAngles(v, ar, ap);
    float gx = v[4] / 65.5f - gbx;
    float gy = v[5] / 65.5f - gby;
    float gz = v[6] / 65.5f - gbz;
    // Quieto = giro filtrado bajo durante STILL_S: reaprender el sesgo (ver STILL_DPS).
    gmag += (sqrt(gx * gx + gy * gy + gz * gz) - gmag) * min(1.0f, dt / 0.05f);
    stillFor = gmag < STILL_DPS ? stillFor + dt : 0;
    still = stillFor >= STILL_S;
    if (still) {
        float a = min(1.0f, dt / BIAS_TAU_S);
        gbx += a * gx;
        gby += a * gy;
        gbz += a * gz;
    }
    // Vertical actual (gravedad filtrada) para separar el giro de voltear del resto.
    float an = sqrt((float)v[0] * v[0] + (float)v[1] * v[1] + (float)v[2] * v[2]);
    if (an > 1000) {
        gux = 0.98f * gux + 0.02f * v[0] / an;
        guy = 0.98f * guy + 0.02f * v[1] / an;
        guz = 0.98f * guz + 0.02f * v[2] / an;
    }
    float gn = sqrt(gux * gux + guy * guy + guz * guz) + 1e-6f;
    float gyawRate = (gx * gux + gy * guy + gz * guz) / gn;
    yawRate = gyawRate;
    float grollRate = gy * ux - gx * uy;
    // Modo apuntar: velocidad de giro (yaw = vertical, pitch = gz), suavizada, y el temblor se
    // atenúa con k = w²/(w²+still²): casi 0 al temblar, casi 1 al girar de verdad.
    fyaw = cfg.smooth * fyaw + (1.0f - cfg.smooth) * gyawRate;
    fpit = cfg.smooth * fpit + (1.0f - cfg.smooth) * gz;
    float w2 = fyaw * fyaw + fpit * fpit;
    float k = w2 / (w2 + cfg.still * cfg.still + 1e-6f);
    if (still) {
        fyaw = fpit = 0;            // quieto: el cursor no se arrastra solo
    } else {
        dYaw += fyaw * k * dt;
        dPit += fpit * k * dt;
    }
    float gyaw = still ? 0 : gyawRate;
    if (fabsf(gyaw) < 0.2f) gyaw = 0;
    yaw += gyaw * dt;
    if (yaw > 180) yaw -= 360;
    else if (yaw < -180) yaw += 360;
    lax = v[0] / 16384.0f;
    lay = v[1] / 16384.0f;
    laz = v[2] / 16384.0f;
    lgx = gx;
    lgy = gy;
    lgz = gz;
    ltemp = v[3] / 333.87f + 21.0f;
    roll = cfg.fuse * (roll + grollRate * dt) + (1.0f - cfg.fuse) * ar;
    pitch = cfg.fuse * (pitch + gz * dt) + (1.0f - cfg.fuse) * ap;
    tr = roll - zr;
    tp = pitch - zp;
    sr = cfg.smooth * sr + (1.0f - cfg.smooth) * tr;
    sp = cfg.smooth * sp + (1.0f - cfg.smooth) * tp;
    if (tr < minR) minR = tr;
    if (tr > maxR) maxR = tr;
    if (tp < minP) minP = tp;
    if (tp > maxP) maxP = tp;
}

void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    rgbLedWrite(RGB_BUILTIN, r, g, b);
#else
    neopixelWrite(RGB_BUILTIN, r, g, b);
#endif
#endif
}

// Aviso a EyeClick: el cursor sale (dx, dy) y vuelve al mismo píxel, y luego igual hacia el
// otro lado (si el cursor está pegado a un borde, una de las dos mitades sí se ve).
void cursorBlip(int dx, int dy) {
    if (!bleMouse.isConnected()) return;
    for (int sign = 1; sign >= -1; sign -= 2) {
        bleMouse.move(sign * dx, sign * dy);
        delay(30);
        bleMouse.move(-sign * dx, -sign * dy);
        delay(30);
    }
}

void checkShake() {
    unsigned long now = millis();
    if (!settling) {
        if (fabsf(yawRate) < SHAKE_DPS) return;
        int s = yawRate > 0 ? 1 : -1;
        if (s == shakeSign) return;
        shakeSign = s;
        if (nTurns == SHAKE_TURNS) {        // ventana deslizante de los últimos cambios de sentido
            for (int i = 1; i < SHAKE_TURNS; i++) turns[i - 1] = turns[i];
            nTurns--;
        }
        turns[nTurns++] = now;
        if (nTurns == SHAKE_TURNS && now - turns[0] <= (unsigned long)(SHAKE_WINDOW_S * 1000)) {
            settling = true;
            settleStart = movingAt = now;
            nTurns = shakeSign = 0;
            accX = accY = 0;
            Serial.println("Sacudida: quedate quieto para calibrar");
            led(40, 30, 0);
            cursorBlip(0, SIGNAL_PX);
        }
        return;
    }
    if (gmag >= SETTLE_DPS) movingAt = now;
    if (now - movingAt >= (unsigned long)(SETTLE_S * 1000)) {
        calibrate();                        // ~1 s, también recentra
        settling = false;
        dYaw = dPit = 0;
        accX = accY = 0;
        Serial.println("Giroscopio calibrado");
        cursorBlip(SIGNAL_PX, 0);
        led(0, 40, 0);
        delay(300);
        led(0, 0, 0);
    } else if (now - settleStart >= (unsigned long)(SETTLE_TIMEOUT_S * 1000)) {
        settling = false;                   // no se quedó quieto: sin calibrar (EyeClick avisa)
        Serial.println("Sacudida sin quietud: no se calibró");
        led(0, 0, 0);
    }
}

// Eje Y invertido de fábrica para este montaje (fijo en el código: no depende de lo
// guardado ni de "Valores de fábrica"). El interruptor "Invertir Y" lo vuelve a voltear.
const bool BASE_INVERT_Y = true;

bool invertY() {
    return BASE_INVERT_Y != cfg.invY;
}

float tiltSpeed(float deg, bool inv) {
    float a = fabs(deg);
    if (a < cfg.dead) return 0;
    float n = constrain((a - cfg.dead) / cfg.range, 0.0f, 1.0f);
    float v = powf(n, cfg.expo) * cfg.speed;
    if (deg < 0) v = -v;
    return inv ? -v : v;
}

String cfgJson() {
    char b[320];
    snprintf(b, sizeof(b),
             "{\"dead\":%.2f,\"range\":%.2f,\"speed\":%.2f,\"expo\":%.2f,\"smooth\":%.3f,\"fuse\":%.4f,\"invX\":%d,\"invY\":%d,\"swap\":%d,\"on\":%d,"
             "\"gain\":%.1f,\"still\":%.2f,\"point\":%d}",
             cfg.dead, cfg.range, cfg.speed, cfg.expo, cfg.smooth, cfg.fuse, cfg.invX, cfg.invY, cfg.swap, cfg.on,
             cfg.gain, cfg.still, cfg.point);
    return String(b);
}

void setup() {
    Serial.begin(115200);
    prefs.begin("cal", false);
    loadCfg();

    Wire.begin(SDA_PIN, SCL_PIN);
    Wire.setClock(400000);
    writeReg(0x6B, 0x00);
    writeReg(0x1B, 0x08);
    writeReg(0x1C, 0x00);
    delay(300);

    Wire.beginTransmission(MPU);
    Wire.write(0x75);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU, (uint8_t)1);
    uint8_t who = Wire.read();
    Serial.printf("WHO_AM_I=0x%02X\n", who);
    // Filtro interno (DLPF) a ~41 Hz y 1 kHz de muestreo: sin esto el giróscopo mide con
    // 250 Hz de ancho de banda y el ruido tapa la detección de "quieto".
    writeReg(0x1A, 0x03);
    writeReg(0x19, 0x00);
    if (who != 0x68) writeReg(0x1D, 0x03);  // MPU-6500/9250: filtro del acelerómetro (no existe en el 6050)

    calibrate();

    startWifi();

    server.on("/", []() { server.send_P(200, "text/html", PAGE); });
    server.on("/d", []() {
        char b[420];
        snprintf(b, sizeof(b),
                 "{\"r\":%.2f,\"p\":%.2f,\"y\":%.2f,\"rmin\":%.1f,\"rmax\":%.1f,\"pmin\":%.1f,\"pmax\":%.1f,"
                 "\"vx\":%.2f,\"vy\":%.2f,\"ble\":%d,"
                 "\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"gx\":%.2f,\"gy\":%.2f,\"gz\":%.2f,\"t\":%.1f}",
                 tr, tp, yaw, minR, maxR, minP, maxP, vx, vy, bleMouse.isConnected() ? 1 : 0,
                 lax, lay, laz, lgx, lgy, lgz, ltemp);
        server.send(200, "application/json", b);
    });
    server.on("/cfg", []() { server.send(200, "application/json", cfgJson()); });
    server.on("/set", []() {
        setKey(server.arg("k"), server.arg("v").toFloat());
        server.send(200, "text/plain", "ok");
    });
    server.on("/save", []() {
        saveCfg();
        server.send(200, "text/plain", "ok");
    });
    server.on("/defaults", []() {
        cfg = Cfg();
        saveCfg();
        server.send(200, "text/plain", "ok");
    });
    server.on("/zero", []() {
        zr = roll;
        zp = pitch;
        yaw = 0;
        sr = sp = 0;
        server.send(200, "text/plain", "ok");
    });
    server.on("/reset", []() {
        minR = maxR = minP = maxP = 0;
        server.send(200, "text/plain", "ok");
    });
    server.on("/calib", []() {
        calibrate();
        server.send(200, "text/plain", "ok");
    });
    server.begin();

    bleMouse.begin();
}

void loop() {
    checkWifi();
    server.handleClient();
    updateTilt();
    checkShake();

    if (cfg.on && bleMouse.isConnected() && !settling) {
        if (cfg.point) {
            float mx = cfg.swap ? dPit : dYaw;
            float my = cfg.swap ? dYaw : dPit;
            vx = (cfg.invX ? -mx : mx) * cfg.gain;
            vy = (invertY() ? -my : my) * cfg.gain;
        } else {
            float tx = cfg.swap ? sp : sr;
            float ty = cfg.swap ? sr : sp;
            vx = tiltSpeed(tx, cfg.invX);
            vy = tiltSpeed(ty, invertY());
        }
        dYaw = dPit = 0;
        accX += vx;
        accY += vy;
        if (millis() - tMove >= MOVE_MS) {
            tMove = millis();
            // Solo se descuenta lo que se envía, así un giro rápido no pierde píxeles.
            int dx = constrain((int)accX, -127, 127), dy = constrain((int)accY, -127, 127);
            accX -= dx;
            accY -= dy;
            if (dx || dy) bleMouse.move(dx, dy);
        }
    } else {
        vx = vy = 0;
        accX = accY = 0;
        dYaw = dPit = 0;
    }

    delay(5);
}