/**
 * motion.js — Framer Motion CDN bridge for htm templates (no build step).
 *
 * The framer-motion UMD build exposes `window.Motion` (motion, AnimatePresence,
 * MotionConfig, useInView, ...). Because this app renders JSX with htm instead
 * of a compiler, this module provides `window.MotionHtm(createElement)`, an
 * htm renderer factory that maps literal tags like <motion.div>,
 * <animatepresence> and <motionconfig> to their Framer Motion components.
 *
 * If the CDN fails to load, MotionHtm falls back to a plain htm renderer and
 * strips Framer-specific props so pages still render (just without motion).
 */
(function () {
  'use strict';

  var FRAMER_PROPS = {
    animate: 1,
    initial: 1,
    exit: 1,
    variants: 1,
    transition: 1,
    whileHover: 1,
    whileTap: 1,
    whileFocus: 1,
    whileInView: 1,
    whileDrag: 1,
    viewport: 1,
    layout: 1,
    layoutId: 1,
    drag: 1,
    dragConstraints: 1,
    dragElastic: 1,
    dragMomentum: 1,
    onDrag: 1,
    onDragStart: 1,
    onDragEnd: 1,
    onAnimationStart: 1,
    onAnimationComplete: 1,
    onViewportEnter: 1,
    onViewportLeave: 1
  };

  function stripFramerProps(props) {
    if (!props) return props || {};
    var out = {};
    for (var key in props) {
      if (Object.prototype.hasOwnProperty.call(props, key) && !FRAMER_PROPS[key]) {
        out[key] = props[key];
      }
    }
    return out;
  }

  window.MotionHtm = function MotionHtm(createElement) {
    var Motion = window.Motion;
    var plain = htm.bind(createElement);

    if (!Motion || !Motion.motion) {
      return plain;
    }

    return htm.bind(function (type, props) {
      var children = Array.prototype.slice.call(arguments, 2);
      if (typeof type === 'string') {
        if (type.indexOf('motion.') === 0) {
          var tag = type.slice(7);
          var comp = Motion.motion[tag];
          return createElement(comp || tag, comp ? props : stripFramerProps(props), children.length ? children : null);
        }
        if (type === 'animatepresence') {
          return createElement(Motion.AnimatePresence, props, children.length ? children : null);
        }
        if (type === 'motionconfig') {
          return createElement(Motion.MotionConfig, props, children.length ? children : null);
        }
      }
      return createElement(type, props, children.length ? children : null);
    });
  };
})();
