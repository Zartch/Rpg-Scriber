/* RPG Scribe - 3D relationship graph (ES module, converted from IIFE) */

import { escapeHtml } from "../utils.js";

export { createRelationshipGraph3D };

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function mixHexColor(hex, amount) {
    var value = String(hex || "#64748b").replace("#", "");
    if (value.length !== 6) return hex || "#64748b";
    var delta = clamp(amount, -1, 1);
    var r = parseInt(value.slice(0, 2), 16);
    var g = parseInt(value.slice(2, 4), 16);
    var b = parseInt(value.slice(4, 6), 16);
    if (delta >= 0) {
      r = Math.round(r + (255 - r) * delta);
      g = Math.round(g + (255 - g) * delta);
      b = Math.round(b + (255 - b) * delta);
    } else {
      r = Math.round(r * (1 + delta));
      g = Math.round(g * (1 + delta));
      b = Math.round(b * (1 + delta));
    }
    return "#" + [r, g, b].map(function (part) {
      return part.toString(16).padStart(2, "0");
    }).join("");
  }

  function formatMetric(value) {
    if (!isFinite(value)) return "0";
    if (Math.abs(value) >= 100) return String(Math.round(value));
    if (Math.abs(value) >= 10) return value.toFixed(1);
    return value.toFixed(2);
  }

  function kindAccent(kind) {
    if (kind === "player") return "#60a5fa";
    if (kind === "npc") return "#f59e0b";
    if (kind === "location") return "#34d399";
    if (kind === "entity") return "#f97316";
    return "#94a3b8";
  }

  function drawNodeShape(ctx, node, x, y, radius, fill, stroke) {
    ctx.beginPath();
    if (node.kind === "npc") {
      ctx.rect(x - radius, y - radius, radius * 2, radius * 2);
    } else if (node.kind === "location") {
      ctx.moveTo(x, y - radius * 1.15);
      ctx.lineTo(x + radius * 1.1, y);
      ctx.lineTo(x, y + radius * 1.15);
      ctx.lineTo(x - radius * 1.1, y);
      ctx.closePath();
    } else if (node.kind === "entity") {
      ctx.moveTo(x - radius * 1.2, y - radius * 0.65);
      ctx.lineTo(x + radius * 1.2, y - radius * 0.65);
      ctx.lineTo(x + radius * 0.75, y + radius * 0.95);
      ctx.lineTo(x - radius * 0.75, y + radius * 0.95);
      ctx.closePath();
    } else {
      ctx.arc(x, y, radius, 0, Math.PI * 2);
    }
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.lineWidth = 1.6;
    ctx.strokeStyle = stroke;
    ctx.stroke();
  }

  function createRelationshipGraph3D(options) {
    if (!options || !options.canvas || !options.root) {
      throw new Error("RelationshipGraph3D requires root and canvas.");
    }

    var canvas = options.canvas;
    var ctx = canvas.getContext("2d");
    if (!ctx) {
      return {
        setVisible: function () {},
        render: function () {},
        resize: function () {},
        destroy: function () {},
      };
    }

    var state = {
      width: 1,
      height: 1,
      pixelRatio: 1,
      visible: false,
      graph: null,
      viewGraph: null,
      hoveredKey: null,
      selectedKey: null,
      dragNodeKey: null,
      dragStartDistance: 0,
      pointer: { x: 0, y: 0 },
      camera: { yaw: 0.45, pitch: -0.32, distance: 700, focal: 560 },
      interaction: { mode: "", startX: 0, startY: 0, startYaw: 0, startPitch: 0, moved: false },
      simulationAlpha: 0,
      rafId: null,
      projectedNodes: [],
      positions: {},
      searchQuery: "",
      communityFilter: "all",
      neighborhoodDepth: 0,
      isolateComponent: false,
      metric: "degree",
      pathSourceKey: "",
      pathTargetKey: "",
      pathEdges: {},
      pathNodes: {},
    };

    function scheduleFrame() {
      if (state.rafId != null) return;
      state.rafId = window.requestAnimationFrame(function () {
        state.rafId = null;
        tick();
      });
    }

    function setTooltip(node, point) {
      if (!options.tooltip || !node || !point) return;
      options.tooltip.classList.remove("hidden");
      options.tooltip.style.left = Math.round(point.x) + "px";
      options.tooltip.style.top = Math.round(point.y) + "px";
      options.tooltip.innerHTML =
        "<strong>" + escapeHtml(node.label || node.id) + "</strong><br>" +
        "Type: " + escapeHtml(node.kind || "unknown") + "<br>" +
        "Community: " + escapeHtml(node.communityLabel || "Unassigned") + "<br>" +
        "Degree: " + escapeHtml(String(node.metrics.degree || 0));
    }

    function hideTooltip() {
      if (!options.tooltip) return;
      options.tooltip.classList.add("hidden");
      options.tooltip.innerHTML = "";
    }

    function resize() {
      var rect = canvas.getBoundingClientRect();
      state.width = Math.max(1, Math.round(rect.width || 1));
      state.height = Math.max(1, Math.round(rect.height || 1));
      state.pixelRatio = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      canvas.width = Math.round(state.width * state.pixelRatio);
      canvas.height = Math.round(state.height * state.pixelRatio);
      ctx.setTransform(state.pixelRatio, 0, 0, state.pixelRatio, 0, 0);
      state.camera.focal = Math.max(460, Math.min(800, state.width * 0.85));
      renderFrame();
    }

    function ensurePosition(nodeId) {
      if (state.positions[nodeId]) return state.positions[nodeId];
      var angleA = Math.random() * Math.PI * 2;
      var angleB = Math.random() * Math.PI * 2;
      var radius = 210 + Math.random() * 150;
      state.positions[nodeId] = {
        x: Math.cos(angleA) * Math.cos(angleB) * radius,
        y: Math.sin(angleB) * radius * 0.8,
        z: Math.sin(angleA) * Math.cos(angleB) * radius,
        vx: 0,
        vy: 0,
        vz: 0,
      };
      return state.positions[nodeId];
    }

    function buildAdjacency(nodes, links) {
      var adjacency = {};
      nodes.forEach(function (node) {
        adjacency[node.id] = [];
      });
      links.forEach(function (link) {
        if (!adjacency[link.source] || !adjacency[link.target]) return;
        adjacency[link.source].push({ key: link.target, link: link });
        adjacency[link.target].push({ key: link.source, link: link });
      });
      return adjacency;
    }

    function connectedComponents(nodes, adjacency) {
      var visited = {};
      var components = [];
      nodes.forEach(function (node) {
        if (visited[node.id]) return;
        var queue = [node.id];
        var component = [];
        visited[node.id] = true;
        while (queue.length) {
          var current = queue.shift();
          component.push(current);
          (adjacency[current] || []).forEach(function (neighbor) {
            if (visited[neighbor.key]) return;
            visited[neighbor.key] = true;
            queue.push(neighbor.key);
          });
        }
        components.push(component);
      });
      return components;
    }

    function detectCommunities(nodes, adjacency) {
      var labels = {};
      nodes.forEach(function (node) {
        labels[node.id] = node.id;
      });
      for (var iteration = 0; iteration < 12; iteration += 1) {
        var changed = false;
        nodes.forEach(function (node) {
          var counts = {};
          (adjacency[node.id] || []).forEach(function (neighbor) {
            var label = labels[neighbor.key];
            counts[label] = (counts[label] || 0) + 1;
          });
          var nextLabel = labels[node.id];
          var bestScore = -1;
          Object.keys(counts).sort().forEach(function (candidate) {
            var score = counts[candidate];
            if (score > bestScore) {
              bestScore = score;
              nextLabel = candidate;
            }
          });
          if (nextLabel !== labels[node.id]) {
            labels[node.id] = nextLabel;
            changed = true;
          }
        });
        if (!changed) break;
      }
      var communityNames = {};
      var communityIds = {};
      var counter = 1;
      nodes.forEach(function (node) {
        var raw = labels[node.id] || node.id;
        if (!communityIds[raw]) {
          communityIds[raw] = String(counter);
          communityNames[communityIds[raw]] = "Community " + counter;
          counter += 1;
        }
        node.community = communityIds[raw];
        node.communityLabel = communityNames[node.community];
      });
    }

    function computeCentrality(nodes, adjacency) {
      var betweenness = {};
      var closeness = {};
      nodes.forEach(function (node) {
        betweenness[node.id] = 0;
      });

      nodes.forEach(function (source) {
        var stack = [];
        var predecessors = {};
        var sigma = {};
        var distance = {};
        nodes.forEach(function (node) {
          predecessors[node.id] = [];
          sigma[node.id] = 0;
          distance[node.id] = -1;
        });
        sigma[source.id] = 1;
        distance[source.id] = 0;
        var queue = [source.id];
        while (queue.length) {
          var vertex = queue.shift();
          stack.push(vertex);
          (adjacency[vertex] || []).forEach(function (neighbor) {
            var target = neighbor.key;
            if (distance[target] < 0) {
              queue.push(target);
              distance[target] = distance[vertex] + 1;
            }
            if (distance[target] === distance[vertex] + 1) {
              sigma[target] += sigma[vertex];
              predecessors[target].push(vertex);
            }
          });
        }

        var totalDistance = 0;
        var reachable = 0;
        Object.keys(distance).forEach(function (nodeId) {
          if (distance[nodeId] > 0) {
            totalDistance += distance[nodeId];
            reachable += 1;
          }
        });
        closeness[source.id] = reachable > 0 && totalDistance > 0 ? (reachable / totalDistance) : 0;

        var dependency = {};
        nodes.forEach(function (node) {
          dependency[node.id] = 0;
        });
        while (stack.length) {
          var current = stack.pop();
          predecessors[current].forEach(function (pred) {
            if (!sigma[current]) return;
            dependency[pred] += (sigma[pred] / sigma[current]) * (1 + dependency[current]);
          });
          if (current !== source.id) {
            betweenness[current] += dependency[current];
          }
        }
      });

      var scale = nodes.length > 2 ? (2 / ((nodes.length - 1) * (nodes.length - 2))) : 1;
      nodes.forEach(function (node) {
        node.metrics = {
          degree: (adjacency[node.id] || []).length,
          betweenness: betweenness[node.id] * scale,
          closeness: closeness[node.id],
        };
      });
    }

    function buildGraph(raw) {
      var rawNodes = (raw && raw.nodes) || [];
      var rawLinks = (raw && raw.links) || [];
      var nodes = rawNodes.map(function (node) {
        return {
          id: node.id,
          label: node.label,
          shortLabel: node.shortLabel,
          kind: node.kind,
          description: node.description || "",
          entityType: node.entityType || "",
          metrics: { degree: 0, betweenness: 0, closeness: 0 },
          component: "",
          community: "",
          communityLabel: "",
          neighborKeys: [],
        };
      });
      var nodeMap = {};
      nodes.forEach(function (node) {
        nodeMap[node.id] = node;
        ensurePosition(node.id);
      });
      var links = rawLinks.filter(function (link) {
        return !!(nodeMap[link.source] && nodeMap[link.target]);
      }).map(function (link, index) {
        return {
          id: link.id || (link.source + "|" + link.target + "|" + index),
          source: link.source,
          target: link.target,
          typeKey: link.typeKey || "unknown",
          typeLabel: link.typeLabel || link.typeKey || "unknown",
          category: link.category || "general",
        };
      });
      var adjacency = buildAdjacency(nodes, links);
      nodes.forEach(function (node) {
        node.neighborKeys = (adjacency[node.id] || []).map(function (entry) { return entry.key; });
      });
      connectedComponents(nodes, adjacency).forEach(function (component, index) {
        component.forEach(function (nodeId) {
          if (nodeMap[nodeId]) nodeMap[nodeId].component = "component-" + (index + 1);
        });
      });
      detectCommunities(nodes, adjacency);
      computeCentrality(nodes, adjacency);
      return {
        nodes: nodes,
        links: links,
        adjacency: adjacency,
        nodeMap: nodeMap,
      };
    }

    function computePath(sourceKey, targetKey, adjacency) {
      var result = { nodes: {}, edges: {}, order: [] };
      if (!sourceKey || !targetKey || !adjacency[sourceKey] || !adjacency[targetKey]) {
        return result;
      }
      var queue = [sourceKey];
      var visited = {};
      var parents = {};
      visited[sourceKey] = true;
      while (queue.length) {
        var current = queue.shift();
        if (current === targetKey) break;
        (adjacency[current] || []).forEach(function (neighbor) {
          if (visited[neighbor.key]) return;
          visited[neighbor.key] = true;
          parents[neighbor.key] = current;
          queue.push(neighbor.key);
        });
      }
      if (!visited[targetKey]) return result;
      var path = [];
      var cursor = targetKey;
      while (cursor) {
        path.push(cursor);
        if (cursor === sourceKey) break;
        cursor = parents[cursor];
      }
      path.reverse();
      path.forEach(function (nodeId, index) {
        result.nodes[nodeId] = true;
        if (index < path.length - 1) {
          result.edges[[nodeId, path[index + 1]].sort().join("|")] = true;
        }
      });
      result.order = path;
      return result;
    }

    function computeCommunityAnchors(nodes) {
      var componentMap = {};
      var nodeAnchors = {};
      nodes.forEach(function (node) {
        if (!componentMap[node.component]) {
          componentMap[node.component] = { nodes: [], communities: {} };
        }
        componentMap[node.component].nodes.push(node);
        if (!componentMap[node.component].communities[node.community]) {
          componentMap[node.component].communities[node.community] = [];
        }
        componentMap[node.component].communities[node.community].push(node);
      });

      var componentKeys = Object.keys(componentMap).sort(function (a, b) {
        return componentMap[b].nodes.length - componentMap[a].nodes.length || a.localeCompare(b);
      });
      var componentRadius = Math.max(360, 260 + componentKeys.length * 120);

      componentKeys.forEach(function (componentId, componentIndex) {
        var component = componentMap[componentId];
        var componentAngle = (Math.PI * 2 * componentIndex) / Math.max(1, componentKeys.length);
        var componentOffset = componentKeys.length === 1 ? 0 : componentRadius;
        var componentAnchor = {
          x: Math.cos(componentAngle) * componentOffset,
          y: componentKeys.length === 1 ? 0 : (((componentIndex % 2) ? 1 : -1) * Math.min(140, 40 + component.nodes.length * 6)),
          z: Math.sin(componentAngle) * componentOffset,
        };
        var communityKeys = Object.keys(component.communities).sort(function (a, b) {
          return component.communities[b].length - component.communities[a].length || a.localeCompare(b);
        });
        var communityRadius = Math.max(110, 70 + communityKeys.length * 44);
        communityKeys.forEach(function (communityId, communityIndex) {
          var communityAngle = (Math.PI * 2 * communityIndex) / Math.max(1, communityKeys.length);
          var communityOffset = communityKeys.length === 1 ? 0 : communityRadius;
          var communityAnchor = {
            x: componentAnchor.x + Math.cos(communityAngle) * communityOffset,
            y: componentAnchor.y + (communityKeys.length === 1 ? 0 : (((communityIndex % 3) - 1) * 55)),
            z: componentAnchor.z + Math.sin(communityAngle) * communityOffset,
          };
          component.communities[communityId].forEach(function (node, nodeIndex) {
            var fanAngle = (Math.PI * 2 * nodeIndex) / Math.max(1, component.communities[communityId].length);
            var fanRadius = Math.min(52, 12 + component.communities[communityId].length * 2.4);
            nodeAnchors[node.id] = {
              x: communityAnchor.x + Math.cos(fanAngle) * fanRadius,
              y: communityAnchor.y + (((nodeIndex % 4) - 1.5) * 10),
              z: communityAnchor.z + Math.sin(fanAngle) * fanRadius,
            };
          });
        });
      });

      return nodeAnchors;
    }

    function graphNode(nodeId) {
      return state.graph && state.graph.nodeMap ? state.graph.nodeMap[nodeId] : null;
    }

    function typeColor(typeKey, fallbackIndex) {
      var colors = [
        "#ff6b6b", "#22c55e", "#3b82f6", "#eab308", "#f97316",
        "#14b8a6", "#a855f7", "#ec4899", "#84cc16", "#06b6d4",
      ];
      var hash = 0;
      String(typeKey || "").split("").forEach(function (ch) {
        hash = ((hash << 5) - hash) + ch.charCodeAt(0);
        hash |= 0;
      });
      var index = fallbackIndex != null ? fallbackIndex : Math.abs(hash) % colors.length;
      return colors[index % colors.length];
    }

    function populateSelect(selectEl, placeholder, nodes, currentValue) {
      if (!selectEl) return;
      selectEl.innerHTML = "";
      var placeholderOpt = document.createElement("option");
      placeholderOpt.value = "";
      placeholderOpt.textContent = placeholder;
      selectEl.appendChild(placeholderOpt);
      nodes.slice().sort(function (a, b) {
        return String(a.label).localeCompare(String(b.label));
      }).forEach(function (node) {
        var option = document.createElement("option");
        option.value = node.id;
        option.textContent = node.label;
        selectEl.appendChild(option);
      });
      var safeValue = String(currentValue || "");
      var exists = false;
      Array.prototype.forEach.call(selectEl.options, function (option) {
        if (option.value === safeValue) exists = true;
      });
      selectEl.value = exists ? safeValue : "";
    }

    function applyViewFilters() {
      if (!state.graph) {
        state.viewGraph = null;
        return;
      }

      var graph = state.graph;
      var visibleNodeMap = {};
      graph.nodes.forEach(function (node) {
        if (state.communityFilter !== "all" && node.community !== state.communityFilter) return;
        if (state.searchQuery) {
          var haystack = [node.label, node.shortLabel, node.description, node.id].join(" ").toLowerCase();
          if (haystack.indexOf(state.searchQuery.toLowerCase()) < 0 && node.id !== state.selectedKey) return;
        }
        visibleNodeMap[node.id] = true;
      });

      if (state.isolateComponent) {
        var chosenComponent = "";
        if (state.selectedKey && graph.nodeMap[state.selectedKey]) {
          chosenComponent = graph.nodeMap[state.selectedKey].component;
        } else {
          var counts = {};
          graph.nodes.forEach(function (node) {
            if (!visibleNodeMap[node.id]) return;
            counts[node.component] = (counts[node.component] || 0) + 1;
          });
          Object.keys(counts).forEach(function (componentId) {
            if (!chosenComponent || counts[componentId] > counts[chosenComponent]) {
              chosenComponent = componentId;
            }
          });
        }
        Object.keys(visibleNodeMap).forEach(function (nodeId) {
          if (graph.nodeMap[nodeId] && graph.nodeMap[nodeId].component !== chosenComponent) {
            delete visibleNodeMap[nodeId];
          }
        });
      }

      if (state.selectedKey && state.neighborhoodDepth > 0 && graph.nodeMap[state.selectedKey]) {
        var neighborhood = {};
        var frontier = [{ id: state.selectedKey, depth: 0 }];
        neighborhood[state.selectedKey] = true;
        while (frontier.length) {
          var current = frontier.shift();
          if (current.depth >= state.neighborhoodDepth) continue;
          (graph.adjacency[current.id] || []).forEach(function (neighbor) {
            if (neighborhood[neighbor.key]) return;
            neighborhood[neighbor.key] = true;
            frontier.push({ id: neighbor.key, depth: current.depth + 1 });
          });
        }
        Object.keys(visibleNodeMap).forEach(function (nodeId) {
          if (!neighborhood[nodeId]) delete visibleNodeMap[nodeId];
        });
      }

      var nodes = graph.nodes.filter(function (node) {
        return !!visibleNodeMap[node.id];
      });
      var nodeSet = {};
      nodes.forEach(function (node) {
        nodeSet[node.id] = true;
      });
      var links = graph.links.filter(function (link) {
        return !!(nodeSet[link.source] && nodeSet[link.target]);
      });
      var adjacency = buildAdjacency(nodes, links);
      var path = computePath(state.pathSourceKey, state.pathTargetKey, adjacency);
      state.pathNodes = path.nodes;
      state.pathEdges = path.edges;
      state.viewGraph = {
        nodes: nodes,
        links: links,
        adjacency: adjacency,
        nodeSet: nodeSet,
      };
    }

    function relationLegend() {
      if (!options.legend) return;
      options.legend.innerHTML = "";
      if (!state.viewGraph || !state.viewGraph.links.length) {
        options.legend.innerHTML = '<span class="relationship-legend-empty">No relationships to draw for current filters.</span>';
        return;
      }
      var seen = {};
      var order = [];
      state.viewGraph.links.forEach(function (link) {
        if (seen[link.typeKey]) return;
        seen[link.typeKey] = true;
        order.push(link);
      });
      order.forEach(function (link, index) {
        var item = document.createElement("span");
        item.className = "relationship-legend-item";
        item.innerHTML =
          '<span class="relationship-legend-swatch" style="background:' + escapeHtml(typeColor(link.typeKey, index)) + '"></span>' +
          "<span>" + escapeHtml(link.typeLabel || link.typeKey) + "</span>";
        options.legend.appendChild(item);
      });
    }

    function updateControls() {
      var graph = state.graph;
      if (!graph) return;
      if (options.communitySelect) {
        var previous = state.communityFilter;
        options.communitySelect.innerHTML = '<option value="all">All communities</option>';
        var communityMap = {};
        graph.nodes.forEach(function (node) {
          communityMap[node.community] = node.communityLabel;
        });
        Object.keys(communityMap).sort(function (a, b) {
          return String(communityMap[a]).localeCompare(String(communityMap[b]));
        }).forEach(function (communityId) {
          var option = document.createElement("option");
          option.value = communityId;
          option.textContent = communityMap[communityId];
          options.communitySelect.appendChild(option);
        });
        var safeValue = String(previous || "");
        var exists = false;
        Array.prototype.forEach.call(options.communitySelect.options, function (option) {
          if (option.value === safeValue) exists = true;
        });
        options.communitySelect.value = exists ? safeValue : "all";
        state.communityFilter = options.communitySelect.value;
      }
      populateSelect(options.pathSourceSelect, "Path source", graph.nodes, state.pathSourceKey);
      populateSelect(options.pathTargetSelect, "Path target", graph.nodes, state.pathTargetKey);
    }

    function updateStats() {
      if (!options.stats) return;
      if (!state.viewGraph || !state.viewGraph.nodes.length) {
        options.stats.innerHTML = '<p class="relationship-graph-empty-copy">No visible nodes.</p>';
        return;
      }
      var nodes = state.viewGraph.nodes;
      var links = state.viewGraph.links;
      var communities = {};
      var components = {};
      var bridgeMax = 0;
      nodes.forEach(function (node) {
        communities[node.community] = true;
        components[node.component] = true;
        bridgeMax = Math.max(bridgeMax, node.metrics.betweenness || 0);
      });
      var cards = [
        { value: nodes.length, label: "Visible nodes" },
        { value: links.length, label: "Visible edges" },
        { value: Object.keys(communities).length, label: "Communities" },
        { value: Object.keys(components).length, label: "Components" },
        { value: bridgeMax ? formatMetric(bridgeMax) : "0", label: "Peak bridge score" },
        { value: state.selectedKey && graphNode(state.selectedKey) ? graphNode(state.selectedKey).communityLabel : "None", label: "Focused community" },
      ];
      options.stats.innerHTML = cards.map(function (card) {
        return '<div class="relationship-graph-stat"><strong>' + escapeHtml(String(card.value)) + '</strong><span>' + escapeHtml(card.label) + "</span></div>";
      }).join("");
    }

    function updateDetails() {
      if (!options.details) return;
      var node = state.selectedKey ? graphNode(state.selectedKey) : null;
      if (!node || (state.viewGraph && !state.viewGraph.nodeSet[node.id])) {
        options.details.innerHTML = '<p class="relationship-graph-empty-copy">Select a node to inspect its relations.</p>';
        return;
      }
      var neighbors = (node.neighborKeys || []).map(function (nodeId) {
        return graphNode(nodeId);
      }).filter(Boolean).slice(0, 12);
      options.details.innerHTML =
        "<h4>" + escapeHtml(node.label) + "</h4>" +
        (node.description ? "<p>" + escapeHtml(node.description) + "</p>" : "") +
        '<div class="relationship-graph-detail-grid">' +
          '<div><strong>Type</strong><span>' + escapeHtml(node.kind) + (node.entityType ? " / " + escapeHtml(node.entityType) : "") + "</span></div>" +
          '<div><strong>Community</strong><span>' + escapeHtml(node.communityLabel) + "</span></div>" +
          '<div><strong>Degree</strong><span>' + escapeHtml(String(node.metrics.degree || 0)) + "</span></div>" +
          '<div><strong>Bridge score</strong><span>' + escapeHtml(formatMetric(node.metrics.betweenness || 0)) + "</span></div>" +
          '<div><strong>Closeness</strong><span>' + escapeHtml(formatMetric(node.metrics.closeness || 0)) + "</span></div>" +
          '<div><strong>Component</strong><span>' + escapeHtml(node.component || "n/a") + "</span></div>" +
        "</div>" +
        '<div class="relationship-graph-neighbors">' +
          (neighbors.length
            ? neighbors.map(function (neighbor) {
                return '<span class="relationship-graph-chip"><span class="relationship-graph-chip-swatch" style="background:' + escapeHtml(kindAccent(neighbor.kind)) + '"></span>' + escapeHtml(neighbor.shortLabel || neighbor.label) + "</span>";
              }).join("")
            : '<span class="relationship-graph-empty-copy">No neighbors.</span>') +
        "</div>";
    }

    function updateTopList() {
      if (!options.topList) return;
      if (!state.viewGraph || !state.viewGraph.nodes.length) {
        options.topList.innerHTML = '<p class="relationship-graph-empty-copy">No visible metrics.</p>';
        return;
      }
      var metric = state.metric || "degree";
      var title = metric === "betweenness" ? "bridge score" : metric;
      var rows = state.viewGraph.nodes.slice().sort(function (a, b) {
        return (b.metrics[metric] || 0) - (a.metrics[metric] || 0);
      }).slice(0, 6);
      options.topList.innerHTML =
        '<div class="relationship-graph-top-list">' +
        rows.map(function (node, index) {
          return '<div class="relationship-graph-top-row">' +
            '<span class="relationship-graph-top-rank">#' + (index + 1) + "</span>" +
            "<span>" + escapeHtml(node.label) + "</span>" +
            '<span class="relationship-graph-top-score" title="' + escapeHtml(title) + '">' + escapeHtml(formatMetric(node.metrics[metric] || 0)) + "</span>" +
          "</div>";
        }).join("") +
        "</div>";
    }

    function updatePathInfo() {
      if (!options.pathOutput) return;
      var source = state.pathSourceKey ? graphNode(state.pathSourceKey) : null;
      var target = state.pathTargetKey ? graphNode(state.pathTargetKey) : null;
      if (!source || !target) {
        options.pathOutput.textContent = "Select two nodes to compute a path.";
        return;
      }
      if (!state.pathNodes[target.id]) {
        options.pathOutput.textContent = "No path found inside the current visible graph.";
        return;
      }
      var order = state.viewGraph ? computePath(source.id, target.id, state.viewGraph.adjacency).order : [];
      options.pathOutput.textContent = order.length
        ? order.map(function (nodeId) {
            var node = graphNode(nodeId);
            return node ? node.shortLabel || node.label : nodeId;
          }).join(" -> ")
        : "No path found inside the current visible graph.";
    }

    function updateEmptyState() {
      if (!options.emptyState) return;
      var emptyText = "";
      if (!state.graph || !state.graph.nodes.length) {
        emptyText = "No entities are available for the current campaign.";
      } else if (!state.viewGraph || !state.viewGraph.nodes.length) {
        emptyText = "No graph nodes match the current graph filters.";
      }
      options.emptyState.textContent = emptyText;
      options.emptyState.classList.toggle("hidden", !emptyText);
    }

    function refreshPanels() {
      relationLegend();
      updateStats();
      updateDetails();
      updateTopList();
      updatePathInfo();
      updateEmptyState();
    }

    function project(point) {
      var yaw = state.camera.yaw;
      var pitch = state.camera.pitch;
      var cosYaw = Math.cos(yaw);
      var sinYaw = Math.sin(yaw);
      var cosPitch = Math.cos(pitch);
      var sinPitch = Math.sin(pitch);
      var x1 = point.x * cosYaw - point.z * sinYaw;
      var z1 = point.x * sinYaw + point.z * cosYaw;
      var y2 = point.y * cosPitch - z1 * sinPitch;
      var z2 = point.y * sinPitch + z1 * cosPitch + state.camera.distance;
      if (z2 < 10) return null;
      var scale = state.camera.focal / z2;
      return {
        x: state.width / 2 + x1 * scale,
        y: state.height / 2 + y2 * scale,
        depth: z2,
        scale: scale,
      };
    }

    function renderFrame() {
      ctx.clearRect(0, 0, state.width, state.height);
      ctx.save();
      ctx.fillStyle = "rgba(255,255,255,0.02)";
      for (var grid = -4; grid <= 4; grid += 1) {
        ctx.fillRect(0, state.height / 2 + grid * 48, state.width, 1);
        ctx.fillRect(state.width / 2 + grid * 48, 0, 1, state.height);
      }
      ctx.restore();

      if (!state.viewGraph || !state.viewGraph.nodes.length) return;

      var projectionCache = {};
      state.projectedNodes = [];
      state.viewGraph.nodes.forEach(function (node) {
        var position = ensurePosition(node.id);
        var projection = project(position);
        if (!projection) return;
        var value = node.metrics[state.metric] || 0;
        var radius = clamp(4.6 + (node.metrics.degree || 0) * 0.72 + value * 9.5, 4.6, 13.5);
        projection.node = node;
        projection.radius = radius * Math.max(0.48, projection.scale * 2.25);
        projectionCache[node.id] = projection;
        state.projectedNodes.push(projection);
      });

      var hoveredKey = state.hoveredKey;
      var selectedKey = state.selectedKey;
      var pathEdges = state.pathEdges || {};
      var pathNodes = state.pathNodes || {};

      state.viewGraph.links.slice().sort(function (a, b) {
        var pa = projectionCache[a.source];
        var pb = projectionCache[a.target];
        var qa = projectionCache[b.source];
        var qb = projectionCache[b.target];
        var da = pa && pb ? ((pa.depth + pb.depth) / 2) : 99999;
        var db = qa && qb ? ((qa.depth + qb.depth) / 2) : 99999;
        return db - da;
      }).forEach(function (link, index) {
        var source = projectionCache[link.source];
        var target = projectionCache[link.target];
        if (!source || !target) return;
        var key = [link.source, link.target].sort().join("|");
        var highlighted = !!(
          pathEdges[key] ||
          (hoveredKey && (link.source === hoveredKey || link.target === hoveredKey)) ||
          (selectedKey && (link.source === selectedKey || link.target === selectedKey))
        );
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(target.x, target.y);
        ctx.lineWidth = highlighted ? 2.5 : 1.1;
        ctx.strokeStyle = highlighted ? typeColor(link.typeKey, index) : "rgba(148, 163, 184, 0.26)";
        ctx.globalAlpha = highlighted ? 0.95 : 0.55;
        ctx.stroke();
        ctx.globalAlpha = 1;
      });

      state.projectedNodes.sort(function (a, b) {
        return b.depth - a.depth;
      }).forEach(function (projection) {
        var node = projection.node;
        var focused = node.id === selectedKey;
        var hovered = node.id === hoveredKey;
        var highlighted = focused || hovered || !!pathNodes[node.id];
        var baseColor = mixHexColor(kindAccent(node.kind), node.community ? (parseInt(node.community, 10) % 5) * 0.08 : 0);
        drawNodeShape(
          ctx,
          node,
          projection.x,
          projection.y,
          projection.radius,
          highlighted ? mixHexColor(baseColor, 0.2) : baseColor,
          highlighted ? "#f8fafc" : mixHexColor(baseColor, -0.45)
        );
        if (highlighted || projection.radius >= 8.5 || state.searchQuery) {
          ctx.fillStyle = highlighted ? "#d7ffe7" : "#b9f8ff";
          ctx.font = (focused ? "700 " : "600 ") + Math.round(clamp(9 + projection.radius * 0.16, 9, 12)) + "px Consolas, 'Lucida Console', monospace";
          ctx.textAlign = "center";
          ctx.fillText(node.shortLabel || node.label, projection.x, projection.y - projection.radius - 8);
        }
      });
    }

    function stepSimulation() {
      if (!state.viewGraph || !state.viewGraph.nodes.length) return;
      var nodes = state.viewGraph.nodes;
      var links = state.viewGraph.links;
      var alpha = state.simulationAlpha;
      if (alpha < 0.002) return;
      var anchors = computeCommunityAnchors(nodes);
      var communityLinks = {};
      var communityPairList = [];

      links.forEach(function (link) {
        var sourceNode = graphNode(link.source);
        var targetNode = graphNode(link.target);
        if (!sourceNode || !targetNode) return;
        if (sourceNode.community === targetNode.community) return;
        var pairKey = [sourceNode.community, targetNode.community].sort().join("|");
        communityLinks[pairKey] = (communityLinks[pairKey] || 0) + 1;
      });

      var centers = {};
      nodes.forEach(function (node) {
        var pos = ensurePosition(node.id);
        if (!centers[node.community]) {
          centers[node.community] = { x: 0, y: 0, z: 0, count: 0 };
        }
        centers[node.community].x += pos.x;
        centers[node.community].y += pos.y;
        centers[node.community].z += pos.z;
        centers[node.community].count += 1;
      });
      Object.keys(centers).forEach(function (communityId) {
        centers[communityId].x /= Math.max(1, centers[communityId].count);
        centers[communityId].y /= Math.max(1, centers[communityId].count);
        centers[communityId].z /= Math.max(1, centers[communityId].count);
      });

      Object.keys(communityLinks).forEach(function (pairKey) {
        var pair = pairKey.split("|");
        if (pair.length !== 2 || !centers[pair[0]] || !centers[pair[1]]) return;
        communityPairList.push({
          a: pair[0],
          b: pair[1],
          count: communityLinks[pairKey],
        });
      });

      communityPairList.forEach(function (pair) {
        var centerA = centers[pair.a];
        var centerB = centers[pair.b];
        var dx = centerB.x - centerA.x;
        var dy = centerB.y - centerA.y;
        var dz = centerB.z - centerA.z;
        var distance = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        var linkWeight = Math.min(4, pair.count);
        var preferredDistance = Math.max(170, 250 - (linkWeight * 24));
        var pull = (distance - preferredDistance) * 0.00042 * alpha * (0.8 + linkWeight * 0.22);
        var nx = dx / distance;
        var ny = dy / distance;
        var nz = dz / distance;
        centerA.x += nx * pull * 110;
        centerA.y += ny * pull * 110;
        centerA.z += nz * pull * 110;
        centerB.x -= nx * pull * 110;
        centerB.y -= ny * pull * 110;
        centerB.z -= nz * pull * 110;
      });

      for (var i = 0; i < nodes.length; i += 1) {
        var aNode = nodes[i];
        var aPos = ensurePosition(aNode.id);
        for (var j = i + 1; j < nodes.length; j += 1) {
          var bNode = nodes[j];
          var bPos = ensurePosition(bNode.id);
          var dx = aPos.x - bPos.x;
          var dy = aPos.y - bPos.y;
          var dz = aPos.z - bPos.z;
          var distSq = dx * dx + dy * dy + dz * dz + 0.01;
          var distance = Math.sqrt(distSq);
          var separationMultiplier = 1;
          if (aNode.component !== bNode.component) separationMultiplier = 3.6;
          else if (aNode.community !== bNode.community) {
            var communityPairKey = [aNode.community, bNode.community].sort().join("|");
            var pairCount = communityLinks[communityPairKey] || 0;
            separationMultiplier = pairCount ? Math.max(1.1, 1.65 - Math.min(0.42, pairCount * 0.12)) : 2.05;
          }
          var force = (4200 * separationMultiplier) / distSq;
          aPos.vx += (dx / distance) * force * alpha * 0.016;
          aPos.vy += (dy / distance) * force * alpha * 0.016;
          aPos.vz += (dz / distance) * force * alpha * 0.016;
          bPos.vx -= (dx / distance) * force * alpha * 0.016;
          bPos.vy -= (dy / distance) * force * alpha * 0.016;
          bPos.vz -= (dz / distance) * force * alpha * 0.016;
        }
      }

      links.forEach(function (link) {
        var source = ensurePosition(link.source);
        var target = ensurePosition(link.target);
        var dx = target.x - source.x;
        var dy = target.y - source.y;
        var dz = target.z - source.z;
        var distance = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        var sourceNode = graphNode(link.source);
        var targetNode = graphNode(link.target);
        var targetDistance = 155;
        if (sourceNode && targetNode && sourceNode.community !== targetNode.community) {
          var pairKey = [sourceNode.community, targetNode.community].sort().join("|");
          var pairCount = communityLinks[pairKey] || 1;
          targetDistance = Math.max(132, 174 - Math.min(28, (pairCount - 1) * 10));
        }
        var spring = (distance - targetDistance) * 0.00078 * alpha;
        var nx = dx / distance;
        var ny = dy / distance;
        var nz = dz / distance;
        source.vx += nx * spring * distance;
        source.vy += ny * spring * distance;
        source.vz += nz * spring * distance;
        target.vx -= nx * spring * distance;
        target.vy -= ny * spring * distance;
        target.vz -= nz * spring * distance;
      });

      nodes.forEach(function (node) {
        var pos = ensurePosition(node.id);
        if (state.dragNodeKey === node.id) return;
        var center = centers[node.community] || { x: 0, y: 0, z: 0 };
        var anchor = anchors[node.id] || center;
        pos.vx += (anchor.x - pos.x) * 0.00072 * alpha;
        pos.vy += (anchor.y - pos.y) * 0.00072 * alpha;
        pos.vz += (anchor.z - pos.z) * 0.00072 * alpha;
        pos.vx += (center.x - pos.x) * 0.00014 * alpha;
        pos.vy += (center.y - pos.y) * 0.00014 * alpha;
        pos.vz += (center.z - pos.z) * 0.00014 * alpha;
        pos.vx += -pos.x * 0.00005 * alpha;
        pos.vy += -pos.y * 0.00005 * alpha;
        pos.vz += -pos.z * 0.00005 * alpha;
        pos.vx *= 0.92;
        pos.vy *= 0.92;
        pos.vz *= 0.92;
        pos.x += pos.vx;
        pos.y += pos.vy;
        pos.z += pos.vz;
      });

      state.simulationAlpha *= 0.985;
    }

    function tick() {
      if (!state.visible) return;
      stepSimulation();
      renderFrame();
      if (state.simulationAlpha > 0.002 || state.interaction.mode || state.hoveredKey) {
        scheduleFrame();
      }
    }

    function nodeAtPoint(x, y) {
      var found = null;
      state.projectedNodes.forEach(function (projection) {
        var dx = projection.x - x;
        var dy = projection.y - y;
        if ((dx * dx) + (dy * dy) <= projection.radius * projection.radius) {
          found = !found || projection.depth < found.depth ? projection : found;
        }
      });
      return found ? found.node : null;
    }

    function requestSimulationWarmup() {
      state.simulationAlpha = 1;
      scheduleFrame();
    }

    function onPointerMove(evt) {
      var rect = canvas.getBoundingClientRect();
      state.pointer.x = evt.clientX - rect.left;
      state.pointer.y = evt.clientY - rect.top;
      if (state.dragNodeKey) {
        var dragged = ensurePosition(state.dragNodeKey);
        var depth = state.dragStartDistance || state.camera.distance;
        var scale = depth / state.camera.focal;
        dragged.x += (evt.movementX || 0) * scale * 1.6;
        dragged.y += (evt.movementY || 0) * scale * 1.6;
        dragged.vx = 0;
        dragged.vy = 0;
        dragged.vz = 0;
        state.interaction.moved = true;
        renderFrame();
        scheduleFrame();
        return;
      }
      if (state.interaction.mode === "orbit") {
        state.camera.yaw = state.interaction.startYaw + ((evt.clientX - state.interaction.startX) * 0.008);
        state.camera.pitch = clamp(state.interaction.startPitch + ((evt.clientY - state.interaction.startY) * 0.008), -1.2, 1.2);
        state.interaction.moved = true;
        scheduleFrame();
        return;
      }
      var hovered = nodeAtPoint(state.pointer.x, state.pointer.y);
      state.hoveredKey = hovered ? hovered.id : null;
      if (hovered) setTooltip(hovered, { x: state.pointer.x, y: state.pointer.y });
      else hideTooltip();
      renderFrame();
    }

    function onPointerDown(evt) {
      canvas.focus();
      var node = nodeAtPoint(state.pointer.x, state.pointer.y);
      state.interaction.startX = evt.clientX;
      state.interaction.startY = evt.clientY;
      state.interaction.startYaw = state.camera.yaw;
      state.interaction.startPitch = state.camera.pitch;
      state.interaction.moved = false;
      if (node) {
        state.dragNodeKey = node.id;
        var projection = state.projectedNodes.find(function (entry) { return entry.node.id === node.id; });
        state.dragStartDistance = projection ? projection.depth : state.camera.distance;
        canvas.classList.add("dragging");
      } else {
        state.interaction.mode = "orbit";
        canvas.classList.add("dragging");
      }
      scheduleFrame();
    }

    function onPointerUp() {
      var dragNodeKey = state.dragNodeKey;
      canvas.classList.remove("dragging");
      state.dragNodeKey = null;
      state.interaction.mode = "";
      if (!state.interaction.moved) {
        var node = nodeAtPoint(state.pointer.x, state.pointer.y);
        if (node) {
          state.selectedKey = node.id === state.selectedKey ? "" : node.id;
          if (state.selectedKey && !state.pathSourceKey) state.pathSourceKey = state.selectedKey;
          if (options.pathSourceSelect) options.pathSourceSelect.value = state.pathSourceKey;
          if (options.pathTargetSelect) options.pathTargetSelect.value = state.pathTargetKey;
          applyViewFilters();
          refreshPanels();
        } else if (state.selectedKey) {
          state.selectedKey = "";
          applyViewFilters();
          refreshPanels();
        }
      }
      state.simulationAlpha = Math.max(state.simulationAlpha, 0.12);
      renderFrame();
    }

    function bindEvents() {
      canvas.addEventListener("mousemove", onPointerMove);
      canvas.addEventListener("mousedown", onPointerDown);
      window.addEventListener("mouseup", onPointerUp);
      canvas.addEventListener("mouseleave", function () {
        if (!state.dragNodeKey && !state.interaction.mode) {
          state.hoveredKey = null;
          hideTooltip();
          renderFrame();
        }
      });
      canvas.addEventListener("wheel", function (evt) {
        evt.preventDefault();
        state.camera.distance = clamp(state.camera.distance + evt.deltaY * 0.55, 220, 1900);
        scheduleFrame();
      }, { passive: false });
      canvas.addEventListener("dblclick", function () {
        var node = nodeAtPoint(state.pointer.x, state.pointer.y);
        if (!node) return;
        state.selectedKey = node.id;
        applyViewFilters();
        refreshPanels();
        requestSimulationWarmup();
      });
      window.addEventListener("resize", resize);

      if (options.searchInput) {
        options.searchInput.addEventListener("input", function () {
          state.searchQuery = options.searchInput.value || "";
          applyViewFilters();
          refreshPanels();
          requestSimulationWarmup();
        });
        options.searchInput.addEventListener("keydown", function (evt) {
          if (evt.key !== "Enter" || !state.graph) return;
          var query = (options.searchInput.value || "").trim().toLowerCase();
          if (!query) return;
          var match = state.graph.nodes.find(function (node) {
            return String(node.label).toLowerCase().indexOf(query) >= 0 ||
              String(node.id).toLowerCase().indexOf(query) >= 0;
          });
          if (!match) return;
          state.selectedKey = match.id;
          if (!state.pathSourceKey) state.pathSourceKey = match.id;
          if (options.pathSourceSelect) options.pathSourceSelect.value = state.pathSourceKey;
          applyViewFilters();
          refreshPanels();
          requestSimulationWarmup();
        });
      }

      if (options.communitySelect) {
        options.communitySelect.addEventListener("change", function () {
          state.communityFilter = options.communitySelect.value || "all";
          applyViewFilters();
          refreshPanels();
          requestSimulationWarmup();
        });
      }

      if (options.neighborhoodSelect) {
        options.neighborhoodSelect.addEventListener("change", function () {
          state.neighborhoodDepth = parseInt(options.neighborhoodSelect.value || "0", 10) || 0;
          applyViewFilters();
          refreshPanels();
          requestSimulationWarmup();
        });
      }

      if (options.isolateCheckbox) {
        options.isolateCheckbox.addEventListener("change", function () {
          state.isolateComponent = !!options.isolateCheckbox.checked;
          applyViewFilters();
          refreshPanels();
          requestSimulationWarmup();
        });
      }

      if (options.metricSelect) {
        options.metricSelect.addEventListener("change", function () {
          state.metric = options.metricSelect.value || "degree";
          updateTopList();
          renderFrame();
        });
      }

      if (options.pathSourceSelect) {
        options.pathSourceSelect.addEventListener("change", function () {
          state.pathSourceKey = options.pathSourceSelect.value || "";
          applyViewFilters();
          refreshPanels();
          renderFrame();
        });
      }

      if (options.pathTargetSelect) {
        options.pathTargetSelect.addEventListener("change", function () {
          state.pathTargetKey = options.pathTargetSelect.value || "";
          applyViewFilters();
          refreshPanels();
          renderFrame();
        });
      }
    }

    bindEvents();
    resize();

    return {
      setVisible: function (visible) {
        state.visible = !!visible;
        if (state.visible) {
          resize();
          scheduleFrame();
        } else {
          hideTooltip();
        }
      },
      render: function (rawGraph) {
        state.graph = buildGraph(rawGraph || { nodes: [], links: [] });
        if (state.selectedKey && !state.graph.nodeMap[state.selectedKey]) state.selectedKey = "";
        if (state.pathSourceKey && !state.graph.nodeMap[state.pathSourceKey]) state.pathSourceKey = "";
        if (state.pathTargetKey && !state.graph.nodeMap[state.pathTargetKey]) state.pathTargetKey = "";
        updateControls();
        applyViewFilters();
        refreshPanels();
        requestSimulationWarmup();
      },
      resize: resize,
      destroy: function () {
        if (state.rafId != null) window.cancelAnimationFrame(state.rafId);
        state.rafId = null;
      },
    };
  }
