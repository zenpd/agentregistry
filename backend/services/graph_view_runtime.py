"""Cobol ContextIntel dependency-graph view runtime, vendored verbatim.

Source: cobol_contextintel/src/cobol_intel/analysis/neo4j_graph_view.py
(MIT License). Drives the pyvis/vis-network iframe: legend-kind filtering,
the right-click hierarchical entry-point view, the context menu and the
parent postMessage protocol (ci:ready / ci:setHidden / ci:filtered /
ci:setFocus / ci:focus). Consumes node attributes `ci_kind` and `ci_entry`.
"""

_BASE_SMOOTH = {"enabled": True, "type": "dynamic"}

_FILTER_RUNTIME_JS = """
(function () {
  "use strict";

  var hiddenKinds = {};       // ci_kind -> true for every kind toggled off
  var focusRoot = null;       // entry point the hierarchical view is rooted at
  var savedPositions = null;  // the physics layout, restored on leaving the view

  var LEVEL_GAP = 170;        // vertical gap between tree levels
  var LEAF_GAP = 190;         // horizontal gap between neighbouring leaves

  // Edge shapes inside the hierarchical view. Branches are drawn straight so the
  // tree reads as a tree; the leftover edges — a call back up to an ancestor, or
  // a second path into a node that already has a parent — curve away so they are
  // visibly not part of the trunk. Straight also sidesteps vis-network's default
  // "dynamic" smoothing, which is driven by invisible support nodes and goes
  // stale the moment the view turns physics off.
  var BRANCH_SMOOTH = { enabled: false };
  var LOOPBACK_SMOOTH = { enabled: true, type: "curvedCW", roundness: 0.35 };
  var BASE_SMOOTH = __BASE_SMOOTH__;  // filled in from _BASE_SMOOTH; see _filter_runtime_js

  function datasets() {
    if (typeof nodes !== "undefined" && nodes && typeof edges !== "undefined" && edges) {
      return { nodes: nodes, edges: edges };
    }
    // Fallback if pyvis ever stops exposing those globals.
    if (typeof network !== "undefined" && network && network.body && network.body.data) {
      return network.body.data;
    }
    return null;
  }

  function net() {
    return typeof network !== "undefined" && network ? network : null;
  }

  function post(msg) {
    if (window.parent && window.parent !== window) window.parent.postMessage(msg, "*");
  }

  // --- hierarchical view ---------------------------------------------------

  // Walks OUT-edges only: the tree answers "what runs when this entry point
  // fires", so the JCL job or CICS screen that *starts* the root is deliberately
  // not part of it. Kinds toggled off in the legend are not traversed either, so
  // hiding data files prunes them out of the tree instead of leaving holes.
  function buildTree(ds, root) {
    var adjacency = {};
    ds.edges.get().forEach(function (e) {
      (adjacency[e.from] = adjacency[e.from] || []).push(e);
    });
    var kindOf = {};
    ds.nodes.get().forEach(function (n) { kindOf[n.id] = n.ci_kind; });

    // Breadth-first, first visit wins: every node ends up with exactly one
    // parent, so recursion and diamonds in the call graph still yield a tree.
    // The edge that first reaches a node becomes its branch; every other edge
    // between two nodes of the tree is a loop-back and is drawn as a curve.
    var order = [root], depth = {}, children = {}, seen = {}, treeEdges = {};
    seen[root] = true;
    depth[root] = 0;
    children[root] = [];
    for (var i = 0; i < order.length; i++) {
      var from = order[i];
      var outs = adjacency[from] || [];
      for (var j = 0; j < outs.length; j++) {
        var to = outs[j].to;
        if (seen[to] === true || hiddenKinds[kindOf[to]] === true) continue;
        seen[to] = true;
        depth[to] = depth[from] + 1;
        children[from].push(to);
        children[to] = [];
        treeEdges[outs[j].id] = true;
        order.push(to);
      }
    }
    return {
      root: root, seen: seen, depth: depth,
      children: children, order: order, treeEdges: treeEdges
    };
  }

  // Classic tidy-tree pass: leaves take the next free column, parents centre
  // over their children. Iterative post-order because a deep PERFORM/CALL chain
  // is exactly the shape that would blow the stack.
  function layoutTree(tree) {
    var pos = {}, nextLeaf = 0;
    var stack = [{ id: tree.root, expanded: false }];
    while (stack.length) {
      var frame = stack.pop();
      var kids = tree.children[frame.id] || [];
      if (kids.length === 0 || frame.expanded) {
        var x = 0;
        if (kids.length === 0) {
          x = nextLeaf * LEAF_GAP;
          nextLeaf++;
        } else {
          for (var k = 0; k < kids.length; k++) x += pos[kids[k]].x;
          x = x / kids.length;
        }
        pos[frame.id] = { x: x, y: tree.depth[frame.id] * LEVEL_GAP };
      } else {
        stack.push({ id: frame.id, expanded: true });
        for (var m = kids.length - 1; m >= 0; m--) stack.push({ id: kids[m], expanded: false });
      }
    }
    // Put the root on x=0 so the tree hangs symmetrically under it.
    var shift = pos[tree.root].x;
    for (var id in pos) pos[id].x -= shift;
    return pos;
  }

  function applyTreeLayout(tree) {
    var n = net();
    if (!n) return;
    var pos = layoutTree(tree);
    // moveNode only sticks while physics is off — setFocus() disables it first.
    for (var id in pos) {
      try { n.moveNode(id, pos[id].x, pos[id].y); } catch (err) { /* node vanished */ }
    }
    try {
      n.fit({ nodes: tree.order, animation: { duration: 400, easingFunction: "easeInOutQuad" } });
    } catch (err) { /* older vis-network without animated fit */ }
  }

  function restoreFullLayout() {
    var n = net();
    if (!n) return;
    if (savedPositions) {
      for (var id in savedPositions) {
        try { n.moveNode(id, savedPositions[id].x, savedPositions[id].y); } catch (err) {}
      }
      savedPositions = null;
    }
    // Restarting from the already-stabilised positions means the graph settles
    // back into the layout the user left rather than re-stabilising from noise.
    n.setOptions({ physics: { enabled: true } });
  }

  function setFocus(root) {
    var ds = datasets();
    if (!ds) return;
    if (root && !ds.nodes.get(root)) root = null;

    var n = net();
    if (root && !focusRoot && n) {
      savedPositions = n.getPositions();
      n.setOptions({ physics: { enabled: false } });
    }
    var leaving = !root && focusRoot;
    focusRoot = root || null;

    var result = applyFilters();
    if (leaving) restoreFullLayout();
    post({
      type: "ci:focus",
      root: focusRoot,
      nodeCount: result ? result.visibleNodes : 0
    });
  }

  // --- filtering -----------------------------------------------------------

  // An edge that has never been styled carries no `smooth` key and is already
  // drawn with BASE_SMOOTH, so leave it alone rather than writing the shape it
  // already has into every edge on the first filter pass.
  function smoothChanged(current, next) {
    if (!current) current = BASE_SMOOTH;
    return current.enabled !== next.enabled || current.type !== next.type;
  }

  function applyFilters() {
    var ds = datasets();
    if (!ds) return null;

    // While focused the tree decides visibility on its own: it was built from
    // the un-hidden kinds already, and the root stays visible even if its kind
    // is toggled off — it is the subject of the view.
    var tree = focusRoot ? buildTree(ds, focusRoot) : null;

    var hiddenNodeIds = {};
    var nodeUpdates = [];
    var visibleNodes = 0;
    ds.nodes.get().forEach(function (n) {
      var isHidden = tree ? tree.seen[n.id] !== true : hiddenKinds[n.ci_kind] === true;
      if (isHidden) hiddenNodeIds[n.id] = true;
      else visibleNodes++;
      if ((n.hidden === true) !== isHidden) nodeUpdates.push({ id: n.id, hidden: isHidden });
    });

    // An edge survives only if BOTH endpoints do, so a hidden node never
    // leaves a dangling arrow pointing at or away from empty space.
    var edgeUpdates = [];
    var visibleEdges = 0;
    ds.edges.get().forEach(function (e) {
      var isHidden = hiddenNodeIds[e.from] === true || hiddenNodeIds[e.to] === true;
      if (!isHidden) visibleEdges++;
      var update = null;
      if ((e.hidden === true) !== isHidden) update = { id: e.id, hidden: isHidden };
      // Only what is on screen gets re-shaped; a hidden edge keeps the baseline
      // so leaving the view has nothing to undo for it.
      var smooth = tree && !isHidden
        ? (tree.treeEdges[e.id] === true ? BRANCH_SMOOTH : LOOPBACK_SMOOTH)
        : BASE_SMOOTH;
      if (smoothChanged(e.smooth, smooth)) {
        update = update || { id: e.id };
        update.smooth = smooth;
      }
      if (update) edgeUpdates.push(update);
    });

    if (nodeUpdates.length) ds.nodes.update(nodeUpdates);
    if (edgeUpdates.length) ds.edges.update(edgeUpdates);
    if (tree) applyTreeLayout(tree);

    post({ type: "ci:filtered", visibleNodes: visibleNodes, visibleEdges: visibleEdges });
    return { visibleNodes: visibleNodes, visibleEdges: visibleEdges };
  }

  // --- context menu --------------------------------------------------------

  // Styled with literal hex inline: this document is generated by pyvis and
  // carries none of the app's stylesheet, for the same reason the node colors
  // in this file are hardcoded.
  var menuEl = null;

  function menu() {
    if (menuEl) return menuEl;
    menuEl = document.createElement("div");
    menuEl.style.cssText =
      "position:fixed; z-index:9999; display:none; min-width:210px; padding:5px;" +
      "background:#ffffff; border:1px solid #e5e7eb; border-radius:8px;" +
      "box-shadow:0 10px 28px rgba(15,23,42,0.18);" +
      "font:600 12.5px/1.4 -apple-system,Segoe UI,Roboto,sans-serif; color:#1f2937;";
    document.body.appendChild(menuEl);
    return menuEl;
  }

  function hideMenu() {
    if (menuEl) menuEl.style.display = "none";
  }

  function showMenu(x, y, items) {
    var el = menu();
    el.innerHTML = "";
    items.forEach(function (item) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = item.label;
      button.style.cssText =
        "display:block; width:100%; text-align:left; padding:7px 10px; border:0;" +
        "border-radius:5px; background:transparent; font:inherit; color:inherit; cursor:pointer;";
      button.onmouseenter = function () { button.style.background = "#f1f5f9"; };
      button.onmouseleave = function () { button.style.background = "transparent"; };
      button.onclick = function () { hideMenu(); item.run(); };
      el.appendChild(button);
    });
    el.style.display = "block";
    // Flip back inside the iframe when the click lands near an edge.
    var width = el.offsetWidth, height = el.offsetHeight;
    el.style.left = Math.max(4, Math.min(x, window.innerWidth - width - 4)) + "px";
    el.style.top = Math.max(4, Math.min(y, window.innerHeight - height - 4)) + "px";
  }

  function bindMenu() {
    var n = net();
    if (!n) return;
    n.on("oncontext", function (params) {
      var ds = datasets();
      var nodeId = n.getNodeAt(params.pointer.DOM);
      var node = ds && nodeId !== undefined && nodeId !== null ? ds.nodes.get(nodeId) : null;
      var items = [];
      if (node && node.ci_entry && node.id !== focusRoot) {
        items.push({
          label: "🌳 Hierarchical view from here",
          run: function () { setFocus(node.id); }
        });
      }
      if (focusRoot) {
        items.push({ label: "↩ Back to the full graph", run: function () { setFocus(null); } });
      }
      if (!items.length) {
        hideMenu();
        return;  // nothing to offer — leave the browser's own menu alone
      }
      params.event.preventDefault();
      showMenu(params.event.clientX, params.event.clientY, items);
    });
    n.on("click", hideMenu);
    n.on("dragStart", hideMenu);
    n.on("zoom", hideMenu);
    window.addEventListener("blur", hideMenu);
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (menuEl && menuEl.style.display === "block") hideMenu();
      else if (focusRoot) setFocus(null);
    });
  }

  // --- parent protocol -----------------------------------------------------

  window.addEventListener("message", function (event) {
    var msg = event.data;
    if (!msg) return;
    if (msg.type === "ci:setHidden") {
      hiddenKinds = {};
      var list = msg.hidden || [];
      for (var i = 0; i < list.length; i++) hiddenKinds[list[i]] = true;
      applyFilters();
    } else if (msg.type === "ci:setFocus") {
      setFocus(msg.root || null);
    }
  });

  bindMenu();

  // A srcdoc iframe gives the parent no reliable "graph is drawn" signal, so
  // announce readiness instead of making the parent guess when to send state.
  post({ type: "ci:ready" });
})();
"""


def _filter_runtime_js() -> str:
    """The runtime as it ships: `_FILTER_RUNTIME_JS` with the placeholders for
    values it shares with the vis options filled in."""
    import json
    return _FILTER_RUNTIME_JS.replace("__BASE_SMOOTH__", json.dumps(_BASE_SMOOTH))


def _inject_filter_runtime(html: str) -> str:
    """Append the legend-filter runtime to the generated pyvis document."""
    script = f"<script type=\"text/javascript\">\n{_filter_runtime_js()}\n</script>\n"
    index = html.rfind("</body>")
    if index == -1:
        return html + script
    return html[:index] + script + html[index:]
