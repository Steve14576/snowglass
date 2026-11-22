/* 独立小样三维视图；所有灰度小块确定生成，不掷骰子或降显示点数。 */
(() => {
  'use strict';
  const loaders = ['https://cdn.jsdelivr.net/npm/three@0.128.0/', 'https://unpkg.com/three@0.128.0/'];
  async function load(path) {
    for (const base of loaders) {
      try {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = base + path; script.onload = resolve; script.onerror = reject;
          document.head.appendChild(script);
        });
        return;
      } catch (_) { /* 主 CDN 失败时只重试这一项。 */ }
    }
    throw new Error('三维依赖加载失败：' + path);
  }
  window.GrayScenes = class {
    static async create(elements) {
      await load('build/three.min.js');
      await load('examples/js/controls/OrbitControls.js');
      return new window.GrayScenes(elements);
    }
    constructor(elements) {
      const T = window.THREE;
      this.syncing = false; this.pending = false; this.views = [];
      for (const element of elements) {
        const renderer = new T.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
        renderer.setClearColor(0, 1);
        renderer.domElement.setAttribute('aria-label', element.getAttribute('aria-label'));
        element.appendChild(renderer.domElement);
        const scene = new T.Scene();
        const camera = new T.PerspectiveCamera(40, 1, .1, 500);
        camera.position.set(38, 26, 49);
        const controls = new T.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = false;
        controls.minDistance = 12; controls.maxDistance = 160;
        controls.update();
        const edgeColor = new T.Color(getComputedStyle(document.querySelector('.muted')).color);
        const edges = new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(16, 16, 32)),
          new T.LineBasicMaterial({color: edgeColor, transparent: true, opacity: .24}));
        scene.add(edges);
        const view = {renderer, scene, camera, controls, element, mesh: null};
        this.views.push(view);
        controls.addEventListener('change', () => this.synchronize(view));
        new ResizeObserver(() => {
          const w = element.clientWidth, h = element.clientHeight;
          renderer.setSize(w, h, false); camera.aspect = w / Math.max(h, 1);
          camera.updateProjectionMatrix(); this.render();
        }).observe(element);
      }
      this.render();
    }
    synchronize(source) {
      if (this.syncing) return;
      this.syncing = true;
      this.views.forEach(view => {
        if (view === source) return;
        view.camera.position.copy(source.camera.position);
        view.controls.target.copy(source.controls.target);
        view.camera.quaternion.copy(source.camera.quaternion);
        view.controls.update();
      });
      this.syncing = false; this.render();
    }
    resetCamera() {
      const view = this.views[0];
      view.camera.position.set(38, 26, 49); view.controls.target.set(0, 0, 0);
      view.controls.update(); this.synchronize(view);
    }
    update(arrays, dims, options) {
      const T = window.THREE, matrix = new T.Matrix4(), color = new T.Color();
      const step = 16 / dims[0], size = step * options.size;
      this.views.forEach((view, v) => {
        if (view.mesh) {
          view.scene.remove(view.mesh); view.mesh.geometry.dispose(); view.mesh.material.dispose();
        }
        const additive = options.mode === 'additive';
        // instanceColor 由 InstancedMesh 自行启用；几何没有逐顶点 color 属性。
        const material = new T.MeshBasicMaterial({
          transparent: additive, opacity: additive ? .18 : 1,
          depthWrite: !additive, depthTest: true,
          blending: additive ? T.AdditiveBlending : T.NormalBlending});
        const mesh = new T.InstancedMesh(new T.BoxGeometry(size, size, size), material, arrays[v].length);
        let count = 0;
        for (let x = 0; x < dims[0]; x++) for (let y = 0; y < dims[1]; y++) for (let z = 0; z < dims[2]; z++) {
          const i = (x * dims[1] + y) * dims[2] + z, g = arrays[v][i];
          if (g <= 0 || (options.slab && [x, y, z][options.axis] !== options.slice)) continue;
          matrix.makeTranslation((x + .5 - dims[0] / 2) * step,
            (y + .5 - dims[1] / 2) * step, (z + .5 - dims[2] / 2) * step);
          mesh.setMatrixAt(count, matrix); mesh.setColorAt(count, color.setRGB(g, g, g)); count++;
        }
        mesh.count = count;
        mesh.instanceMatrix.needsUpdate = true;
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
        mesh.frustumCulled = false;
        view.scene.add(mesh); view.mesh = mesh;
      });
      this.render();
    }
    render() {
      if (this.pending) return;
      this.pending = true;
      requestAnimationFrame(() => {
        this.pending = false;
        this.views.forEach(v => v.renderer.render(v.scene, v.camera));
      });
    }
  };
})();
