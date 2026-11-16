# bluepuff app (Expo: iOS, Android and web)

Tabs: **Race** (race call per start for your class, shift/tack and rig advice, live club sensor),
**Water** (tide times, chop, waves, stream, wind against tide), **Regatta** (club regatta pages),
**Club** (join by club code, follow up to three venues, pick your class, notices) and **Race office**
(officers only: starts against each fleet's limits with a gust-vs-limit chart, course axis, send the
call to members, programme, fleet limits, regatta pages, officers and coaches).

```bash
npm install
EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo start      # press w for web, or scan with Expo Go
npx tsc --noEmit                                              # typecheck
```

The server is in `../server` (`uvicorn server.app:app`). Push notices need a development or store
build with an EAS project id in `app.json` (`extra.eas.projectId`); they are skipped on web.
