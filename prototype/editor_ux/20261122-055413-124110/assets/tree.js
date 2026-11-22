/* 对象树只改变操作归属，源层号／张量身份不变。 */
(() => {
  'use strict';
  class Tree {
    constructor(model,data,select,reparent){this.model=model;this.data=data;this.select=select;this.reparent=reparent;this.open=new Set(['project','work','text','layer-16','refs']);this.selected=[];
      this.element=document.getElementById('tree');document.getElementById('tree-search').oninput=()=>this.render();}
    render(){
      const M=this.model,query=document.getElementById('tree-search').value.trim().toLowerCase(),shown=new Set();
      if(query)for(const n of M.nodes.values()){const source=M.topo.blocks.find(b=>b.id===n.sourceId);if((n.id+' '+n.name+' '+JSON.stringify(source?.tensors||[])).toLowerCase().includes(query)){shown.add(n.id);M.ancestors(n.id).forEach(id=>shown.add(id));}}
      const scroll=this.element.scrollTop;this.element.textContent='';
      const append=(id,depth)=>{
        if(query&&!shown.has(id))return;const n=M.nodes.get(id),children=M.children(id),row=document.createElement('div');
        row.className='tree-row'+(this.selected.includes(id)?' selected':'');row.dataset.id=id;row.setAttribute('role','treeitem');row.setAttribute('aria-selected',String(this.selected.includes(id)));row.setAttribute('aria-level',String(depth+1));row.tabIndex=this.selected.includes(id)?0:-1;row.style.paddingLeft=depth*13+'px';
        const expanded=query||this.open.has(id);if(children.length)row.setAttribute('aria-expanded',String(!!expanded));
        const disclose=document.createElement('button');disclose.className='disclose';disclose.textContent=children.length?(expanded?'▾':'▸'):'';disclose.tabIndex=-1;disclose.setAttribute('aria-label','展开／折叠 '+n.name);
        disclose.onclick=e=>{e.stopPropagation();if(this.open.has(id))this.open.delete(id);else this.open.add(id);this.render();};row.append(disclose);
        const state=document.createElement('span');state.className='tree-state'+(n.type==='block'&&this.data.groups.has(n.sourceId)?' real':'');state.title=n.type==='block'?(this.data.groups.has(n.sourceId)?'已有真实统计缓存':'未计算／权重未收录'):n.type;row.append(state);
        const name=document.createElement('span');name.className='tree-name';name.textContent=n.name;name.title=n.id;row.append(name);
        if(n.type==='global'||n.type==='group'||n.type==='ghost'){const tag=document.createElement('span');tag.className='tree-kind';tag.textContent={global:'全局',group:'组',ghost:'毛坯'}[n.type];row.append(tag);}
        const count=Object.keys(n.overrides).length;if(count||M.primaryGhost===id){const tag=document.createElement('span');tag.className='tree-badge';tag.textContent=M.primaryGhost===id?'主参照':count+'项覆盖';row.append(tag);}
        row.onclick=e=>this.select([id],e.shiftKey||e.ctrlKey);row.ondblclick=()=>{this.open.has(id)?this.open.delete(id):this.open.add(id);this.render();};
        row.draggable=!['project','global','work','text','vision','refs'].includes(id);
        row.ondragstart=e=>{e.dataTransfer.setData('text/plain',JSON.stringify(this.selected.includes(id)?M.roots(this.selected):[id]));e.dataTransfer.effectAllowed='move';};
        row.ondragover=e=>{if(['root','tower','layer','group','reference'].includes(n.type)){e.preventDefault();row.classList.add('dragover');}};
        row.ondragleave=()=>row.classList.remove('dragover');row.ondrop=e=>{e.preventDefault();row.classList.remove('dragover');try{this.reparent(JSON.parse(e.dataTransfer.getData('text/plain')),id);}catch(error){document.getElementById('status').textContent=error.message;}};
        row.onkeydown=e=>{const rows=[...this.element.querySelectorAll('.tree-row')],i=rows.indexOf(row);if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();rows[Math.max(0,Math.min(rows.length-1,i+(e.key==='ArrowDown'?1:-1)))].focus();}
          if(e.key==='Enter'||e.key===' '){e.preventDefault();this.select([id],e.shiftKey);}if(e.key==='ArrowRight'){this.open.add(id);this.render();}if(e.key==='ArrowLeft'){this.open.delete(id);this.render();}};
        this.element.append(row);if(children.length&&expanded)children.forEach(c=>append(c.id,depth+1));
      };append('project',0);this.element.scrollTop=scroll;
    }
    selection(ids){this.selected=ids;ids.forEach(id=>this.model.ancestors(id).forEach(a=>this.open.add(a)));this.render();if(ids.length===1)this.element.querySelector(`[data-id="${CSS.escape(ids[0])}"]`)?.scrollIntoView({block:'nearest'});}
  }
  window.UXTree=Tree;
})();
