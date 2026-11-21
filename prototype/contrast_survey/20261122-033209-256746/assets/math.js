/* 独立灰度窗口；只映射已有数值，不删除格子。 */
(() => {
  'use strict';
  const clip=v=>Math.max(0,Math.min(1,v));
  function windowGray(v,low,high,reference,gamma=1) {
    if(![v,low,high,reference,gamma].every(Number.isFinite)||gamma<=0)throw Error('灰度参数无效');
    if(high<low)throw Error('白端必须大于或等于黑端');
    const value=high>low?clip((v-low)/(high-low)):(reference>0?clip(v/reference):0);
    return Math.pow(value,gamma);
  }
  function arrays(part,tensor,channel,s) {
    const used=part[channel]===null||part[channel]===undefined?'full':channel;
    const raw=part[used],w=tensor.windows[used],r=tensor.reference_white;
    const baseLow=s.window==='robust'?w.p005:w.low,baseHigh=s.window==='robust'?w.p995:w.high;
    const span=baseHigh-baseLow;
    const low=baseLow+(+s.black)*span,high=baseLow+(+s.white)*span;
    if(!w.constant&&high<=low)throw Error('右列窗口无效：白端必须高于黑端');
    const result=[raw.map(v=>r>0?clip((+s.oldgain)*v/r):0),part.expanded[used].slice(),
      raw.map(v=>windowGray(v,low,high,r,+s.gamma))];
    return {arrays:result,raw,used,window:w,manual:[low,high],amplification:w.high>w.low?r/(w.high-w.low):null};
  }
  window.ContrastMath={windowGray,arrays};
})();
