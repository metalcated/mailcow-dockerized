// Custom SOGo JS

// Change the visible font-size in the editor, this does not change the font of a html message by default
if (window.CKEDITOR && typeof window.CKEDITOR.addCss === 'function') {
  window.CKEDITOR.addCss("body {font-size: 16px !important}");
}

// Enable scayt by default
//CKEDITOR.config.scayt_autoStartup = true;

// Default rendered message bodies to dark without persisting a mailbox preference.
(function() {
  'use strict';

  var darkPreview = true;
  var refreshQueued = false;

  function updateToggle(button) {
    var icon = button.querySelector('md-icon');
    var label = darkPreview ? 'Use light message preview' : 'Use dark message preview';

    button.setAttribute('aria-label', label);
    button.setAttribute('aria-pressed', darkPreview ? 'true' : 'false');
    button.setAttribute('title', label);
    icon.textContent = darkPreview ? 'brightness_7' : 'brightness_4';
  }

  function createToggle(detailView) {
    var button = document.createElement('button');
    var icon = document.createElement('md-icon');

    button.type = 'button';
    button.className = 'md-button md-icon-button sg-preview-theme-toggle';
    icon.className = 'material-icons';
    button.appendChild(icon);
    button.addEventListener('click', function(event) {
      event.preventDefault();
      event.stopPropagation();
      darkPreview = !darkPreview;
      refreshPreviews();
    });
    detailView.insertBefore(button, detailView.firstChild);

    return button;
  }

  function findToggle(detailView) {
    var children = detailView.children;
    var i;

    for (i = 0; i < children.length; i++) {
      if (children[i].classList.contains('sg-preview-theme-toggle')) {
        return children[i];
      }
    }

    return null;
  }

  function refreshPreview(detailView) {
    var button = findToggle(detailView);
    var hasMessage = !!detailView.querySelector('.mailer_mailcontent .sg-mail-part');

    if (!button) {
      button = createToggle(detailView);
    }

    button.hidden = !hasMessage;
    detailView.classList.toggle('sg-dark-mail-preview', darkPreview && hasMessage);
    detailView.classList.toggle('sg-light-mail-preview', !darkPreview && hasMessage);
    updateToggle(button);
  }

  function refreshPreviews() {
    Array.prototype.forEach.call(
      document.querySelectorAll('#detailView'),
      refreshPreview
    );
  }

  function queueRefresh() {
    if (refreshQueued) {
      return;
    }

    refreshQueued = true;
    window.requestAnimationFrame(function() {
      refreshQueued = false;
      refreshPreviews();
    });
  }

  function startPreviewObserver() {
    refreshPreviews();
    new MutationObserver(queueRefresh).observe(document.body, {
      childList: true,
      subtree: true
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startPreviewObserver, { once: true });
  }
  else {
    startPreviewObserver();
  }
})();
