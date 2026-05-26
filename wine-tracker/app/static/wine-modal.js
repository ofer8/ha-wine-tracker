/**
 * wine-modal.js - Shared functions for the wine add/edit modal.
 *
 * Expects global variables (defined inline before this script loads):
 *   T       - translation object
 *   INGRESS - HA ingress base path (string)
 *
 * Provides:
 *   previewImg(), rotateWineImage(), deleteWineImage(),
 *   getWineFormState(), isWineFormDirty(), tryCloseWineModal(),
 *   toggleVivinoIdPopover(), closeVivinoIdPopover(),
 *   updateVivinoIdFromPopover(), updateVivinoIdTestLink()
 */

/* global T, closeModal */

// ── Dirty-tracking ────────────────────────────────────────────────────────────
var wineFormSnapshot = '';

function getWineFormState() {
  var fields = ['wine_name','wine_year','wine_qty','wine_type','wine_region',
                'wine_notes','wine_purchased_at','wine_price','wine_drink_from',
                'wine_drink_until','wine_location','wine_grape','wine_bottle_format'];
  var parts = fields.map(function(id) { return document.getElementById(id).value; });
  for (var i = 1; i <= 5; i++) {
    var el = document.getElementById('wine_star' + i);
    if (el && el.checked) { parts.push('star' + i); break; }
  }
  var fi = document.querySelector('#winePreview input[type=file]');
  if (fi && fi.value) parts.push('file:' + fi.value);
  return parts.join('|');
}

function isWineFormDirty() {
  return getWineFormState() !== wineFormSnapshot;
}

function tryCloseWineModal() {
  if (isWineFormDirty()) {
    if (!confirm(T.confirm_discard)) return;
  }
  closeModal('wineModal');
}

// ── Image helpers ─────────────────────────────────────────────────────────────

function previewImg(input, previewId) {
  var preview = document.getElementById(previewId);
  var file = (input.files && input.files[0]) ? input.files[0] : null;
  if (!file) return;
  var reader = new FileReader();
  reader.onload = function(e) {
    var img = preview.querySelector('img');
    if (!img) { img = document.createElement('img'); preview.prepend(img); }
    img.src = e.target.result;
    preview.childNodes.forEach(function(n) { if (n.nodeType === 3) n.remove(); });
    var cam = preview.querySelector('.mdi-camera');
    if (cam) cam.style.display = 'none';
    var actions = document.getElementById('imgActions');
    if (actions) actions.style.display = '';
  };
  reader.readAsDataURL(file);
}

function rotateWineImage() {
  var preview = document.getElementById('winePreview');
  var img = preview.querySelector('img');
  if (!img) return;
  var tempImg = new Image();
  tempImg.crossOrigin = 'anonymous';
  tempImg.onload = function() {
    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');
    canvas.width = tempImg.naturalHeight;
    canvas.height = tempImg.naturalWidth;
    ctx.translate(canvas.width, 0);
    ctx.rotate(Math.PI / 2);
    ctx.drawImage(tempImg, 0, 0);
    img.src = canvas.toDataURL('image/jpeg', 0.85);
    canvas.toBlob(function(blob) {
      var file = new File([blob], 'rotated.jpg', { type: 'image/jpeg' });
      var dt = new DataTransfer();
      dt.items.add(file);
      preview.querySelector('input[type=file]').files = dt.files;
    }, 'image/jpeg', 0.85);
  };
  tempImg.src = img.src;
}

function deleteWineImage() {
  if (!confirm('Delete photo?')) return;
  document.getElementById('deleteImageField').value = '1';
  var preview = document.getElementById('winePreview');
  var img = preview.querySelector('img');
  if (img) img.remove();
  var cam = preview.querySelector('.mdi-camera');
  if (cam) { cam.style.display = ''; }
  else {
    cam = document.createElement('i');
    cam.className = 'mdi mdi-camera';
    cam.style.cssText = 'font-size:2rem; opacity:.5';
    preview.insertBefore(cam, preview.firstChild);
  }
  document.getElementById('imgActions').style.display = 'none';
}

// ── Vivino ID popover ─────────────────────────────────────────────────────────

function toggleVivinoIdPopover() {
  var pop = document.getElementById('vivinoIdPopover');
  if (!pop) return;
  var isOpen = pop.style.display === 'none' || !pop.style.display;
  pop.style.display = isOpen ? '' : 'none';
  if (isOpen) {
    var val = document.getElementById('wine_vivino_id').value || '';
    document.getElementById('vivinoIdInput').value = val;
    updateVivinoIdTestLink(val);
    document.getElementById('vivinoIdInput').focus();
  }
}

function closeVivinoIdPopover() {
  var pop = document.getElementById('vivinoIdPopover');
  if (pop) pop.style.display = 'none';
}

function updateVivinoIdFromPopover() {
  var val = document.getElementById('vivinoIdInput').value.trim();
  document.getElementById('wine_vivino_id').value = val;
  updateVivinoIdTestLink(val);
}

function updateVivinoIdTestLink(val) {
  var link = document.getElementById('vivinoIdTestLink');
  if (!link) return;
  if (val) {
    link.href = 'https://www.vivino.com/w/' + val;
    link.style.display = '';
  } else {
    link.style.display = 'none';
  }
}

// Close Vivino-ID popover on outside click
document.addEventListener('click', function(e) {
  var vwrap = document.getElementById('vivinoIdWrap');
  if (vwrap && !vwrap.contains(e.target)) closeVivinoIdPopover();
});
