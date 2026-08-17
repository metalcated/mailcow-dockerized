# mailcow: dockerized - 🐮 + 🐋 = 💕

[![Translation status](https://translate.mailcow.email/widgets/mailcow-dockerized/-/translation/svg-badge.svg)](https://translate.mailcow.email/engage/mailcow-dockerized/)
[![Twitter URL](https://img.shields.io/twitter/url/https/twitter.com/mailcow_email.svg?style=social&label=Follow%20%40mailcow_email)](https://twitter.com/mailcow_email)
![Mastodon Follow](https://img.shields.io/mastodon/follow/109388212176073348?domain=https%3A%2F%2Fmailcow.social&label=Follow%20%40doncow%40mailcow.social&link=https%3A%2F%2Fmailcow.social%2F%40doncow)

## About this fork

This fork maintains a tested Mailcow deployment line that preserves the New Outlook interoperability required by the current installation while continuing to incorporate applicable upstream security fixes and component updates.

The `legacy` branch is the production integration branch. The `master` branch is retained for comparison with upstream Mailcow and is not deployed directly because it includes architectural changes that have not passed this fork's New Outlook compatibility testing.

### Maintenance process

Updates are handled as a staged monthly process:

1. Review new upstream commits, releases, and security advisories.
2. Backport compatible source and configuration fixes to a feature branch created from `legacy`.
3. Update container images individually and verify each change before continuing.
4. Test the Mailcow UI, SOGo, inbound and outbound mail flow, authentication, and existing New Outlook connections.
5. Merge the fully tested feature branch back into `legacy` with a merge commit.

Postfix, database schema, proxy, routing, and autodiscover changes are treated as high risk. They are tested last, with a current server snapshot and a documented rollback path, because a container rollback does not necessarily reverse a database migration.

This process does not imply that `legacy` automatically contains every upstream change or fixes every published CVE. Security changes are reviewed and tracked individually, and compatibility-sensitive changes remain pending until they can be validated without breaking the production mail workflow.


## Want to support mailcow?

Please [consider a support contract with Servercow](https://www.servercow.de/mailcow?lang=en#support) to support further development. _We_ support _you_ while _you_ support _us_. :)

You can also [get a SAL](https://www.servercow.de/mailcow?lang=en#sal) which is a one-time payment with no liabilities or returning fees.

Or just spread the word: moo.

## Info, documentation and support

Please see [the official documentation](https://docs.mailcow.email/) for installation and support instructions. 🐄

🐛 **If you found a critical security issue, please mail us to [info at servercow.de](mailto:info@servercow.de).**

## Cowmunity

[mailcow community](https://community.mailcow.email)

[Telegram mailcow channel](https://telegram.me/mailcow)

[Telegram mailcow Off-Topic channel](https://t.me/mailcowOfftopic)

[Official 𝕏 (Twitter) Account](https://twitter.com/mailcow_email)

[Official Mastodon Account](https://mailcow.social/@doncow)

Telegram desktop clients are available for [multiple platforms](https://desktop.telegram.org). You can search the groups history for keywords.

## Misc

**Important**: mailcow makes use of various open-source software. Please assure you agree with their license before using mailcow.
Any part of mailcow itself is released under **GNU General Public License, Version 3**.

mailcow is a registered word mark of The Infrastructure Company GmbH, Parkstr. 42, 47877 Willich, Germany.

The project is managed and maintained by The Infrastructure Company GmbH.

Originated from @andryyy (André)
