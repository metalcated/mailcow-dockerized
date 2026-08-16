(function() {
  'use strict';

  angular.module('SOGo.Common')
    .config(configure);

  configure.$inject = ['$mdThemingProvider'];

  function configure($mdThemingProvider) {
    var darkBackground = $mdThemingProvider.extendPalette('grey', {
      '200': '242a30',
      '300': '20262b',
      '400': '353c43',
      '500': '9ba6af',
      '600': 'b5bec5',
      '700': 'd0d6db',
      '800': '181d22',
      '900': '12161a',
      'A100': '2b3238',
      'A200': '30373e',
      'A400': '1c2126',
      'A700': '111519',
      '1000': '796b47',
      'contrastDefaultColor': 'light',
      'contrastDarkColors': ['50', '100', '500', '600', '700']
    });
    var neutralAccent = $mdThemingProvider.extendPalette('blue-grey', {
      '500': '46515b',
      '600': '3d474f',
      '700': '343c43',
      '800': '2b3238',
      '900': '22282d',
      'A100': '77838d',
      'A200': '606b74',
      'A400': '46515b',
      'A700': '343c43',
      'contrastDefaultColor': 'light',
      'contrastDarkColors': ['50', '100', '200', '300']
    });

    $mdThemingProvider.definePalette('mailcow-dark', darkBackground);
    $mdThemingProvider.definePalette('mailcow-neutral', neutralAccent);

    $mdThemingProvider.registerStyles([
      '.sg-message-thread {',
      '  background-color: #30373e;',
      '}',
      '.sg-message-thread-first {',
      '  background-color: #3d474f;',
      '}',
      '.sg-quota md-progress-linear .md-container {',
      '  background-color: #30373e;',
      '}',
      '.sg-quota md-progress-linear .md-bar {',
      '  background-color: #77838d;',
      '}',
      '.sg-quota .md-fg.md-primary {',
      '  color: #9ba6af;',
      '}',
      '#detailView {',
      '  position: relative;',
      '}',
      '#detailView .sg-preview-theme-toggle {',
      '  position: absolute;',
      '  top: 8px;',
      '  right: 8px;',
      '  z-index: 20;',
      '  width: 40px;',
      '  min-width: 40px;',
      '  height: 40px;',
      '  min-height: 40px;',
      '  margin: 0;',
      '  padding: 0;',
      '  background-color: #30373e;',
      '  border: 1px solid #46515b;',
      '  border-radius: 50%;',
      '  color: #d0d6db;',
      '  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);',
      '}',
      '#detailView .sg-preview-theme-toggle:hover,',
      '#detailView .sg-preview-theme-toggle:focus {',
      '  background-color: #46515b;',
      '}',
      '#detailView .sg-preview-theme-toggle:focus-visible {',
      '  outline: 2px solid #d0d6db;',
      '  outline-offset: 2px;',
      '}',
      '#detailView .sg-preview-theme-toggle md-icon {',
      '  color: #d0d6db;',
      '}',
      '#detailView .sg-preview-theme-toggle[hidden] {',
      '  display: none;',
      '}',
      '#detailView.sg-dark-mail-preview,',
      '#detailView.sg-dark-mail-preview .mailer_mailcontent {',
      '  background-color: #252b31;',
      '  color-scheme: dark;',
      '}',
      '#detailView.sg-dark-mail-preview .sg-face > md-card,',
      '#detailView.sg-dark-mail-preview .sg-face > md-card > md-card-content {',
      '  background-color: #30373e !important;',
      '  color: #d0d6db;',
      '}',
      '#detailView.sg-dark-mail-preview .sg-face > md-card > md-card-actions {',
      '  background-color: #3d474f !important;',
      '  color: #d0d6db;',
      '}',
      '#detailView.sg-dark-mail-preview md-card-content a {',
      '  color: #b8c0c7 !important;',
      '}',
      '#detailView.sg-dark-mail-preview md-card-content md-chip {',
      '  background-color: #46515b !important;',
      '  color: #d0d6db !important;',
      '}',
      '#detailView.sg-dark-mail-preview .pseudo-input-label,',
      '#detailView.sg-dark-mail-preview .msg-date {',
      '  color: #9ba6af !important;',
      '}',
      '#detailView.sg-dark-mail-preview .sg-mail-part {',
      '  background-color: #f5f5f5 !important;',
      '  color: #111 !important;',
      '  filter: invert(1) hue-rotate(180deg) contrast(0.62);',
      '}',
      '#detailView.sg-dark-mail-preview .sg-mail-part img,',
      '#detailView.sg-dark-mail-preview .sg-mail-part video,',
      '#detailView.sg-dark-mail-preview .sg-mail-part canvas,',
      '#detailView.sg-dark-mail-preview .sg-mail-part svg {',
      '  filter: invert(1) hue-rotate(180deg) contrast(1.6129);',
      '}',
      '@media print {',
      '  #detailView .sg-preview-theme-toggle {',
      '    display: none;',
      '  }',
      '  #detailView.sg-dark-mail-preview .sg-mail-part {',
      '    background-color: #fff !important;',
      '    color: #000 !important;',
      '    filter: none;',
      '  }',
      '  #detailView.sg-dark-mail-preview .sg-mail-part img,',
      '  #detailView.sg-dark-mail-preview .sg-mail-part video,',
      '  #detailView.sg-dark-mail-preview .sg-mail-part canvas,',
      '  #detailView.sg-dark-mail-preview .sg-mail-part svg {',
      '    filter: none;',
      '  }',
      '}'
    ].join(''));

    $mdThemingProvider.theme('default')
      .primaryPalette('blue', {
        'default': '800',
        'hue-1': '700',
        'hue-2': '900',
        'hue-3': 'A700'
      })
      .accentPalette('mailcow-neutral', {
        'default': '700',
        'hue-1': '500',
        'hue-2': '800',
        'hue-3': '900'
      })
      .backgroundPalette('mailcow-dark')
      .dark();
  }
})();
