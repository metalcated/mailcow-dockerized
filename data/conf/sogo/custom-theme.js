(function() {
  'use strict';

  angular.module('SOGo.Common')
    .config(configure);

  configure.$inject = ['$mdThemingProvider'];

  function configure($mdThemingProvider) {
    $mdThemingProvider.theme('default')
      .primaryPalette('sogo-blue', {
        'default': '900',
        'hue-1': '700',
        'hue-2': '800',
        'hue-3': 'A700'
      })
      .accentPalette('amber', {
        'default': 'A200',
        'hue-1': '200',
        'hue-2': 'A400',
        'hue-3': 'A700'
      })
      .backgroundPalette('sogo-grey')
      .dark();

    // The bundled theme stylesheet is light, so generate the dark rules at startup.
    $mdThemingProvider.generateThemesOnDemand(false);
  }
})();
