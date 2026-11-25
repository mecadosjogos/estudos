/* Guia interativo (study/guia_interativo.py). Porta de page.js do gerador
   "resumo-penal": progresso por aula (chave no <html data-gi-key>), tema
   compartilhado entre os guias. Saltos com scrollTo instantâneo e
   deslocamento = barra + níveis da trilha; só scroll-padding-top no CSS. */
(function(){
'use strict';
var $=function(s,r){return (r||document).querySelector(s)};
var $$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
var KEY=document.documentElement.getAttribute('data-gi-key')||'guia-interativo-progresso';
var THEME='guia-interativo-tema';
var store={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}},del:function(k){try{localStorage.removeItem(k)}catch(e){}}};

/* ---------- theme ---------- */
var root=document.documentElement;
function curDark(){var t=root.getAttribute('data-theme');if(t)return t==='dark';return window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches}
$('#bTheme').addEventListener('click',function(){var d=!curDark();root.setAttribute('data-theme',d?'dark':'light');store.set(THEME,d?'dark':'light')});

/* ---------- drawer ---------- */
var side=$('#side'),scrim=$('#scrim'),bMenu=$('#bMenu');
function openSide(){side.classList.add('open');scrim.hidden=false;bMenu.setAttribute('aria-expanded','true')}
function closeSide(){side.classList.remove('open');scrim.hidden=true;bMenu.setAttribute('aria-expanded','false')}
bMenu.addEventListener('click',openSide);$('#bClose').addEventListener('click',closeSide);scrim.addEventListener('click',closeSide);
$('#bProg').addEventListener('click',function(){if(window.innerWidth<1100)openSide();else side.scrollTop=0});

/* ---------- navigation ---------- */
var ROW=21,TPAD=6;function HH(){return $('#topbar').offsetHeight}
function elFor(id){
 if(id==='topo')return $('#topo');
 return document.getElementById('t-'+id.replace(/\./g,'-'))||document.getElementById(id);
}
function openAncestors(el){var p=el.parentElement;while(p){if(p.tagName==='DETAILS'&&!p.open)p.open=true;p=p.parentElement}}
function goTo(id,flash){
 var el=elFor(id);if(!el)return;
 openAncestors(el);closeSide();
 requestAnimationFrame(function(){
  var tp=el.classList.contains('topic')?el:(el.closest('.topic')||el);
  var tid=tp.getAttribute('data-id');
  var lv=tid?tid.split('.').length:(id==='mapa'?1:0);
  var off=HH()+(lv?lv*ROW+TPAD:0)+5;
  window.scrollTo(0,el.getBoundingClientRect().top+window.scrollY-off);
 });
 if(history.replaceState)history.replaceState(null,'','#'+el.id);
 if(flash){el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash')}
}
document.addEventListener('click',function(e){
 var a=e.target.closest&&e.target.closest('[data-go]');
 if(!a)return;
 e.preventDefault();e.stopPropagation();
 goTo(a.getAttribute('data-go'),true);
},true);

/* ---------- progress ---------- */
var done={};try{(JSON.parse(store.get(KEY)||'[]')||[]).forEach(function(i){done[i]=1})}catch(e){}
var boxes=$$('.chk input');
var total=boxes.length;
function save(){store.set(KEY,JSON.stringify(Object.keys(done)))}
function chOf(id){return id.split('.')[0]}
function refresh(){
 var n=0,per={},tot={};
 boxes.forEach(function(b){var id=b.getAttribute('data-id'),c=chOf(id);tot[c]=(tot[c]||0)+1;var on=!!done[id];b.checked=on;var art=b.closest('.topic');if(art)art.classList.toggle('done',on);if(on){n++;per[c]=(per[c]||0)+1}});
 var pct=total?Math.round(n*100/total):0;
 $('#pct').textContent=pct+'%';$('#pbarI').style.width=pct+'%';$('#sideBar').style.width=pct+'%';$('#sideN').textContent=n;
 $('#bProg').setAttribute('aria-label','Progresso geral: '+n+' de '+total+' tópicos ('+pct+'%)');
 $$('[data-ch]').forEach(function(x){
  var c=x.getAttribute('data-ch'),t=tot[c]||0,d=per[c]||0,i=x.querySelector('.cpb i'),tx=x.querySelector('.cpt');
  if(i)i.style.width=(t?d*100/t:0)+'%';if(tx)tx.textContent=d+'/'+t+(x.classList.contains('chprog')?' tópicos estudados neste capítulo':x.classList.contains('mhd')?' estudados':'');
 });
 $$('.mdot[data-dot]').forEach(function(d){d.classList.toggle('ok',!!done[d.getAttribute('data-dot')])});
}
boxes.forEach(function(b){b.addEventListener('change',function(){var id=b.getAttribute('data-id');if(b.checked)done[id]=1;else delete done[id];save();refresh()})});
$('#bReset').addEventListener('click',function(){if(confirm('Zerar todo o progresso salvo neste aparelho?')){done={};store.del(KEY);refresh()}});
refresh();

/* ---------- mind map ---------- */
var mgrid=$('.mgrid');
var dirty=true;
function placeBranch(){
 if(!mgrid)return;
 var open=mgrid.querySelector('.mbr:not([hidden])');if(!open)return;
 var ch=open.getAttribute('data-mbr');var tiles=$$('.mtile',mgrid);
 var idx=-1;tiles.forEach(function(t,i){if(t.getAttribute('data-mch')===ch)idx=i});
 var cols=getComputedStyle(mgrid).gridTemplateColumns.split(' ').filter(Boolean).length||2;
 var end=Math.min(tiles.length-1,Math.floor(idx/cols)*cols+cols-1);
 tiles[end].after(open);
}
if(mgrid)mgrid.addEventListener('click',function(e){
 var rw=e.target.closest('.mrw');
 if(rw){
  var li=rw.parentNode,ul=li.querySelector(':scope > .mkids'),was=rw.classList.contains('sel');
  var y0=rw.getBoundingClientRect().top;
  $$('.mrw.sel',mgrid).forEach(function(x){x.classList.remove('sel')});
  if(ul){var op=ul.hidden;ul.hidden=!op;rw.setAttribute('aria-expanded',op?'true':'false')}
  if(!was)rw.classList.add('sel');
  var dy=rw.getBoundingClientRect().top-y0;if(Math.abs(dy)>1)window.scrollBy(0,dy);
  dirty=true;return;
 }
 var t=e.target.closest('.mtile[data-mch]');if(!t)return;
 var ch=t.getAttribute('data-mch');var p=mgrid.querySelector('.mbr[data-mbr="'+ch+'"]');var wasOpen=!p.hidden;
 $$('.mbr',mgrid).forEach(function(x){x.hidden=true});$$('.mtile',mgrid).forEach(function(x){x.setAttribute('aria-expanded','false')});
 if(!wasOpen){p.hidden=false;t.setAttribute('aria-expanded','true');placeBranch()}
 dirty=true;
});
window.addEventListener('resize',placeBranch);

/* ---------- where am I + back to top ---------- */
var topicsEl=$$('.topic'),tops=[];
var titles={};topicsEl.forEach(function(t){var h=t.querySelector('.tt');titles[t.getAttribute('data-id')]=h?h.textContent.replace(/\s+/g,' ').trim():''});
var lvl=topicsEl.map(function(t){return t.getAttribute('data-id').split('.').length});
function measure(){tops=topicsEl.map(function(t){return t.getBoundingClientRect().top+window.scrollY});dirty=false}
document.addEventListener('toggle',function(){dirty=true},true);
window.addEventListener('resize',function(){dirty=true});
var lastH=0;window.addEventListener('load',function(){dirty=true;onScroll()});
var lastId=null,ticking=false,totop=$('#totop');
var tocLinks={};$$('.toc a[data-go]').forEach(function(a){tocLinks[a.getAttribute('data-go')]=a});
function onScroll(){
 ticking=false;var H=document.body.scrollHeight;if(H!==lastH){lastH=H;dirty=true}if(dirty)measure();
 var base=window.scrollY+HH()+6,y=base+6*ROW+TPAD,lo=0,hi=tops.length-1,k=-1;
 while(lo<=hi){var m=(lo+hi)>>1;if(tops[m]<=y){k=m;lo=m+1}else hi=m-1}
 while(k>=0&&tops[k]>base+lvl[k]*ROW+TPAD+2)k--;
 totop.hidden=window.scrollY<700;
 var id=k>=0?topicsEl[k].getAttribute('data-id'):null;
 if(!id){var mp=$('#mapa');if(mp&&mp.getBoundingClientRect().top<=HH()+ROW+TPAD+8)id='mapa';}
 if(id===lastId)return;lastId=id;
 renderTrail(id);
 $$('.toc a.cur').forEach(function(a){a.classList.remove('cur')});
 if(!id||id==='mapa')return;
 var path=id.split('.');
 var best=null;for(var j=path.length;j>=1&&!best;j--){best=tocLinks[path.slice(0,j).join('.')]}
 if(best)best.classList.add('cur');
}
function renderTrail(id){
 var tr=$('#trail');tr.innerHTML='';
 if(id==='mapa'){
  var m=document.createElement('button');m.type='button';m.className='tr cur';m.setAttribute('data-go','mapa');m.style.paddingLeft='12px';
  m.innerHTML='<span class="n">◆</span><span class="t">Mapa mental</span>';tr.appendChild(m);
 } else if(id){
  var path=id.split('.');
  for(var i=1;i<=path.length;i++){
   var p=path.slice(0,i).join('.');
   var b=document.createElement('button');b.type='button';b.className='tr'+(i===path.length?' cur':'');
   b.setAttribute('data-go',p);b.style.paddingLeft=(12+(i-1)*8)+'px';
   b.title=titles[p]||p;
   b.innerHTML='<span class="n"></span><span class="t"></span>';
   b.firstChild.textContent=p;b.lastChild.textContent=(titles[p]||'').replace(/^[\d.]+\s*/,'');
   tr.appendChild(b);
  }
 }
 root.style.setProperty('--th',tr.offsetHeight+'px');
}
window.addEventListener('scroll',function(){if(!ticking){ticking=true;requestAnimationFrame(onScroll)}},{passive:true});
totop.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'})});
onScroll();

/* ---------- search ---------- */
var sp=$('#search'),qi=$('#q'),res=$('#sres'),info=$('#sinfo'),index=null;
function normCh(c){
 var n=c.normalize?c.normalize('NFD').replace(/[̀-ͯ]/g,''):c;
 n=n.toLowerCase();
 if(n==='º'||n==='°'||n==='ª')return '';
 if(/[\s.,;:()“”"'’‘«»\-–—\/\[\]]/.test(n))return ' ';
 return n;
}
function normalize(s){
 var out='',map=[],prevSpace=true;
 for(var i=0;i<s.length;i++){
  var n=normCh(s[i]);
  for(var j=0;j<n.length;j++){var ch=n[j];if(ch===' '){if(prevSpace)continue;prevSpace=true}else prevSpace=false;out+=ch;map.push(i)}
 }
 return {t:out,m:map};
}
function build(){
 index=[];
 $$('.sb').forEach(function(el){
  if(el.parentElement&&el.parentElement.closest('.sb')&&!el.classList.contains('tt'))return; // nested: outer already indexed
  var txt=el.textContent.replace(/\s+/g,' ').trim();if(!txt)return;
  var topic=el.closest('.topic');var id=topic?topic.getAttribute('data-id'):'';
  var where=el.closest('details.full')?'texto completo':el.closest('details.qs')?'perguntas de aluno':el.closest('.exs')?'exemplo':el.closest('.vis')?'visual':el.classList.contains('tt')?'título':'resumo';
  var nn=normalize(txt);
  index.push({el:el,id:id,txt:txt,n:nn.t,m:nn.m,w:where});
 });
}
function esc(s){return s.replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})}
function run(){
 var q=qi.value;var nq=normalize(q).t.trim();
 res.innerHTML='';
 if(nq.length<2){info.textContent='Digite pelo menos 2 letras. A busca inclui o texto escondido nos “ver mais”.';return}
 if(!index)build();
 var out=[],count=0;
 for(var i=0;i<index.length;i++){
  var it=index[i],p=it.n.indexOf(nq);
  if(p<0)continue;count++;
  if(out.length<120){
   var s=it.m[p],e=it.m[Math.min(p+nq.length-1,it.m.length-1)]+1;
   var a=Math.max(0,s-70),b=Math.min(it.txt.length,e+90);
   var snip=(a>0?'…':'')+esc(it.txt.slice(a,s))+'<mark>'+esc(it.txt.slice(s,e))+'</mark>'+esc(it.txt.slice(e,b))+(b<it.txt.length?'…':'');
   out.push({k:i,html:snip,id:it.id,w:it.w});
  }
 }
 info.textContent=count?(count+' trecho'+(count>1?'s':'')+' encontrado'+(count>1?'s':'')+(count>out.length?' — mostrando os '+out.length+' primeiros':'')):'Nada encontrado.';
 var frag=document.createDocumentFragment();
 out.forEach(function(r){
  var li=document.createElement('li'),b=document.createElement('button');
  b.type='button';
  b.innerHTML='<span class="rt">'+esc(r.id?(r.id+' · '+(titles[r.id]||'').replace(/^[\d.]+\s*/,'')):'Início')+'</span><span class="rw">'+r.w+'</span><div class="rs">'+r.html+'</div>';
  b.addEventListener('click',function(){jump(index[r.k].el)});
  li.appendChild(b);frag.appendChild(li);
 });
 res.appendChild(frag);
}
function jump(el){
 closeSearch();
 openAncestors(el);
 setTimeout(function(){
  el.scrollIntoView({block:'center'});
  el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');
 },30);
}
var deb;qi.addEventListener('input',function(){clearTimeout(deb);deb=setTimeout(run,160)});
qi.addEventListener('keydown',function(e){if(e.key==='Enter'){clearTimeout(deb);run();var f=res.querySelector('button');if(f&&e.shiftKey)f.click()}});
function openSearch(){sp.hidden=false;document.body.style.overflow='hidden';setTimeout(function(){qi.focus();qi.select()},20)}
function closeSearch(){sp.hidden=true;document.body.style.overflow=''}
$('#bSearch').addEventListener('click',openSearch);$('#bSClose').addEventListener('click',closeSearch);
document.addEventListener('keydown',function(e){
 if(e.key==='Escape'){if(!sp.hidden)closeSearch();else closeSide()}
 if((e.key==='/'||(e.key==='k'&&(e.ctrlKey||e.metaKey)))&&sp.hidden&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();openSearch()}
});

/* ---------- initial hash ---------- */
if(location.hash.length>1){var h=decodeURIComponent(location.hash.slice(1));var t=document.getElementById(h);if(t){openAncestors(t);setTimeout(function(){t.scrollIntoView()},50)}}
})();
