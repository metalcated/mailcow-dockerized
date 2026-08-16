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
    var mutedAmber = $mdThemingProvider.extendPalette('amber', {
      '500': '9d6c22',
      '600': '90601d',
      '700': '82551a',
      '800': '704714',
      '900': '5d390f',
      'contrastDefaultColor': 'light',
      'contrastDarkColors': ['50', '100', '200', '300', '400', 'A100', 'A200']
    });

    $mdThemingProvider.definePalette('mailcow-dark', darkBackground);
    $mdThemingProvider.definePalette('mailcow-amber', mutedAmber);

    $mdThemingProvider.theme('default')
      .primaryPalette('blue', {
        'default': '800',
        'hue-1': '700',
        'hue-2': '900',
        'hue-3': 'A700'
      })
      .accentPalette('mailcow-amber', {
        'default': '700',
        'hue-1': '500',
        'hue-2': '800',
        'hue-3': '900'
      })
      .backgroundPalette('mailcow-dark')
      .dark();
  }
})();
