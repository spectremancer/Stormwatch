# Quick start
## How do I get started with Stormwatch?
1. Use Add in the left panel to create a location such as Home.
2. Find your city or ZIP code, confirm the map pin, name the profile, and save it.
3. Select the weather event types to monitor for that profile.
4. Configure sound, speech, and desktop preferences. Repeat for other locations if needed.
5. Choose a refresh interval, then click Start monitoring.
6. Check Active Alerts and Map, and confirm the connection health information shows a recent successful refresh.
The application must remain running and the computer must be awake to obtain new alerts.

## What does each main tab do?
Locations manages saved places and their preferences. Active Alerts shows currently relevant alerts. Alert Feed shows alert changes as a readable stream. Map shows affected areas, saved pins, and optional radar. Notifications explains channel delivery and failures. History searches your locally stored alert records and downloaded historical records.

## What is a good first notification setup?
Start with your own location and a small set of important event types. Under Alerts → Sound Settings…, choose Tornado + hurricane if those are the only events you want to sound. Under Alerts → Speech Settings…, enable speech and select its event types separately. Use Alerts → Test Notification… to preview your devices before relying on automatic delivery.

## How do I avoid receiving alerts for the whole United States?
Give each enabled profile a state, county, or resolved coordinate location. An enabled profile with no geographic restrictions matches nationwide alerts of its selected types. Inspect every enabled profile, since all enabled profiles monitor together.

## How do I learn the app without receiving real notifications?
Open Tools → Demo Mode. Leave the real sound and desktop preview options unchecked. Demo scenarios use isolated simulated data; they do not populate live history or change your real location settings. Use this Documentation window offline whenever you need instructions.

## Can Stormwatch replace official emergency instructions?
Use it to organize NWS information and follow your local emergency authorities' instructions. A sleeping computer, a disconnected network, muted speakers, or operating-system notification settings can prevent delivery. Read the full official alert text for actions, timing, and affected areas rather than relying solely on a sound or spoken summary.

# Locations & profiles
## How do I add Home, Work, or Family locations?
Click Add in the sidebar. Search for a US city or ZIP code, select a result, and confirm the approximate map pin. You can pan and zoom and click to move the pin. Give the profile a useful name and select its events and notification preferences before saving. The final geographic resolution uses the NWS service and needs a connection.

## How accurate is the city or ZIP search?
The bundled offline catalog contains about 41,000 US postal-place records. Results are approximate area centers, not street-address geocoding. Confirm and adjust the pin, especially for large rural ZIP areas or cities with the same name. Use the base five-digit ZIP code; the catalog is not a ZIP+4 address database.

## How do I configure states or counties directly?
Use the advanced location editor available from the location workflow, or Edit for an existing profile. Enter comma-separated two-letter state codes, such as IL, IN. County codes are NWS UGC codes such as ILC031, not county names or ZIP codes. Enter the states before using Choose counties to find counties for those states.

## How are state, county, and coordinate filters combined?
Restrictions on the same profile must all match. A state filter plus an unrelated county or coordinate can prevent expected alerts. For alternatives such as Home in Illinois and Family in Florida, create separate enabled profiles instead of combining incompatible restrictions in one profile.

## How do coordinate locations match alerts without polygons?
Stormwatch uses an alert polygon when one is available. When it is absent, resolved NWS affected zones can provide the geographic match. A zone may be wider than the immediate threat area. A location that cannot be resolved is not saved as a successfully configured coordinate profile.

## Does choosing a profile stop monitoring the others?
No. The sidebar selector chooses whose event and notification settings you are editing. All enabled profiles monitor together. To stop monitoring a particular profile, Edit it and turn off Monitor this location.

## How do I rename, disable, or remove a location?
Select the profile, then Edit to change its name, geography, or enabled state. Remove asks for confirmation. You must retain at least one saved profile; disable a profile if you want to keep its settings without monitoring it. Existing history retains the location association recorded at the time.

## Will overlapping locations produce duplicate sounds?
Successful delivery is tracked per alert version and channel, so an overlapping match does not repeatedly play a successfully delivered version. The app still records the profile matches and reasons separately. Use Why did I get this? to understand which profiles matched and how their rules applied.

# Event selection
## How do I choose which warnings and watches to monitor?
Select a saved profile in the left panel, then check its Event types list. Select all and Clear affect that profile. Settings are saved automatically. Repeat for other profiles as needed; each profile can have a different selection.

## What does the selected event count mean?
It counts the event types checked for the profile currently selected in the sidebar. It is not the number of active alerts, the number of affected locations, or the total selections across every enabled profile.

## Are warnings, watches, advisories, and statements supported?
The shared catalog includes weather and environmental warnings, watches, advisories, statements, outlooks, forecasts, and related weather types. Civil, administrative, and test messages are outside the weather catalog. An event appearing in the catalog does not mean NWS currently has an active alert of that type.

## What happens when a new event type becomes available?
Newly discovered supported types can appear in the selection list unchecked. Review your profiles if you want to start monitoring them. An explicit notification event list remains a separate restriction; selecting a monitored type does not automatically add it to an explicit sound or speech allowlist.

## Why am I seeing an alert I did not select in the current profile?
Another enabled profile may select it. Check the alert's matching locations and Why did I get this? explanation, then review each enabled profile. A nationwide profile can match broadly even when your currently selected profile is local.

## Can I display many types but sound only for tornadoes?
Yes. Check all desired monitored types in the sidebar, then use Alerts → Sound Settings… to restrict sound independently. Sound filtering does not remove cards or history, and it does not configure speech or desktop delivery.

# Monitoring & refresh
## How do I start, pause, and refresh monitoring?
Click Start monitoring in the sidebar or use Monitoring → Start Monitoring. Pause with the same control or Monitoring → Pause Monitoring. While running and not already fetching, press F5 or choose Monitoring → Refresh Now for an immediate NWS refresh.

## How do I change the NWS refresh interval?
Pause monitoring, then choose 30, 60, 90, or 120 seconds using the sidebar selector or Monitoring → Refresh Interval. Start again to use it. The selection persists across sessions. Radar has its own refresh schedule and does not follow this NWS interval.

## Does a 30-second interval mean exactly two requests every minute?
The next scheduled refresh follows completion of the current fetch and processing, so slow requests can extend the time between results. The app avoids overlapping NWS fetches. A failed request also waits for the configured interval before the next scheduled attempt.

## What happens on the first successful refresh?
Existing non-critical alerts normally populate quietly. Previously unseen tornado and hurricane watches or warnings can still receive sound or desktop delivery when their rules allow. Speech uses a stricter cutoff: only eligible NWS issue timestamps after this monitoring session started can be announced. Missing or unusable issue timestamps remain silent for speech.

## What happens when I pause and resume?
Pausing stops live polling and stops pending speech. Existing views remain as last-known information, with local expiry cleanup continuing. Resuming establishes a new speech start cutoff; older already-issued events are not read as a startup backlog.

## Why is Refresh Now unavailable?
It requires monitoring to be running and no refresh already in progress. Start monitoring or wait for the current fetch to finish. Repeated clicks do not create a queue of duplicate network requests.

# Connection health
## How do I know the app is receiving fresh information?
Read the connection health display for the last successful NWS refresh, next refresh countdown, errors, and coverage notices. The top-right green Monitoring label means the polling loop is enabled; it alone does not confirm a successful connection.

## What do the red and green status colors mean?
Red Paused means live monitoring is paused. Green Monitoring means it is running. Check the separate health information for actual freshness, failures, or incomplete coverage. Radar can succeed while NWS fails, or vice versa, because they use different services.

## When is information considered stale?
The health display flags paused monitoring, refresh errors, or a last success older than the larger of 120 seconds and twice the configured interval. Review the displayed timestamp before treating last-known cards as a current picture.

## What happens if NWS fails or the internet goes down?
The app keeps the last-known alert snapshot rather than treating a failed fetch as a cancellation. Known expiration times still remove expired cards and map areas locally. A later successful refresh updates the snapshot. There is no new live coverage while the connection is unavailable.

## What does a coverage notice mean?
A successful active-alert fetch can still have incomplete cancellation coverage. Such a notice is distinct from a complete refresh failure. Read the notice and timestamp together, and use official NWS information if you need to verify a particular alert's current state.

## How do I investigate a persistent connection problem?
Use Tools → Diagnostics… for application and connection state, and Tools → Open Log Folder for logs. For radar, also open Map → Connection details. Record the actual error and time. Check network access, system clock, proxy or firewall configuration, and provider availability before changing app settings.

# Active alerts
## How do I read an active-alert card?
Cards summarize the event type, affected location, severity, issue information, and expiration countdown. Open the alert details for the full message, instructions, source, and delivery explanation. A short summary or countdown does not replace the official alert's timing and instructions.

## How are active alerts sorted?
Warnings appear before watches, followed by other event classes. Within those groups, higher severity comes first. Remaining ties use expiration from longest/latest to shortest/earliest; unknown expiration comes last. This is a priority ordering, not chronological arrival order.

## Why do I see only some cards at once?
Active alerts are paginated in groups of 20 to keep the interface responsive during busy weather. Use the page controls to see additional cards. Pagination does not stop monitoring or limit the number of stored relevant alerts.

## How are cancellations and expirations cleaned up?
Cancellation and supersession updates remove obsolete active versions. A local timer also checks expiration times every second, so known expired alerts leave both cards and map even between API refreshes. Their recorded history remains available.

## Which expiration time is used when an alert has several times?
Cleanup uses the earliest valid ends or expires time available for that alert. The displayed countdown is based on that effective expiration. Missing times cannot provide a reliable countdown and are ordered after known times.

## What does the location overview show?
It summarizes the highest relevant threat for each monitored profile. Multiple profiles can refer to the same underlying alert. Use individual cards and their full details to distinguish affected areas and official instructions.

# Alert feed
## What belongs in the Alert Feed?
The feed contains alert changes, such as new alerts, meaningful updates, extensions, cancellations, and expirations. General polling chatter and ordinary non-alert data are kept out of the chat-style feed. Use connection health and diagnostics for operational information.

## How do I clear the feed?
Use Clear feed in the feed view or Alerts → Clear Alert Feed. This clears the visible stream; it does not delete stored history, reset processed-version tracking, or make successful notifications replay.

## Why do older feed messages disappear?
The visible feed is bounded to about 4,000 lines to avoid indefinite interface growth. Search History for retained records instead of treating the feed as the complete archive.

## Does an update to a known alert appear again?
A meaningful new version can create a new feed record and independent notification decisions. An unchanged version is not repeatedly processed as a new alert. Merely enriching geographic outlines does not count as a new alert-content version.

## What do extension, superseded, and no-longer-active mean?
An extension changes the alert's timing. Superseded means an old version has been replaced by newer information. No-longer-active means it has left the current active set. Cancellation and expiration describe specific ending conditions. These changes are historical information, not all new threats.

# Map navigation
## How do I move around the map?
Drag to pan, use the mouse wheel or + and − to zoom, and double-click to zoom in. Click an alert outline to inspect its details. Saved-location pins help relate the displayed weather to your profiles.

## What area does the map show by default?
It starts centered on North America. The offline land outlines include the whole world, so you can pan or zoom out for global context. NWS alert coverage remains US-focused; global outlines do not add international alert feeds.

## What does Fit do?
With displayed alerts, Fit frames their geometry and enabled saved-location pins. With no displayed events, Fit returns to North America even if saved pins exist. The location-setup map has its own behavior for fitting the location being edited.

## Why is an active alert missing an outline?
Some alerts do not have an explicit polygon. Stormwatch can use resolved NWS zone geometry when available, but missing or unavailable geometry can leave a card without a useful outline. Check Active Alerts and the full area description; a blank map is not proof there is no alert.

## Are the outlines predicted storm tracks?
No. They are NWS affected polygons or zone boundaries. Radar is a separate observation layer. Neither a warning boundary nor an animated radar frame is a forecast storm track generated by Stormwatch.

## How do I export the map?
Use File → Export Map Image… to save a PNG of the visible map canvas. It captures the current view and radar frame rather than exporting GIS geometry. Keep the map unobstructed; desktop screenshot permissions or capture support may be required on your platform.

# Radar & playback
## How do I turn on radar?
Open Map and enable Show recent radar. The app retrieves RainViewer metadata and recent radar frames. Radar is optional and has a refresh cycle separate from NWS alerts. If it fails, inspect Connection details for the actual request state and error.

## What do Play, Previous frame, and Next frame do?
Play animates the available recent frames; Pause stops playback. Previous frame and Next frame move through the loaded sequence. These are recent past observations, not a forecast or a guarantee of the storm's next movement.

## What time is shown for radar?
Radar timestamps are in UTC, alongside frame position, age, and any staleness information. Alert text and spoken expiration times use the computer's local time. Radar composites can contain observations of different ages; compare timestamps before drawing conclusions.

## How often does radar refresh?
Its automatic metadata and imagery cycle is approximately every five minutes while enabled. Refresh radar requests an update explicitly. Changing the 30–120 second NWS interval does not change RainViewer's schedule or generate newer observations.

## Why does imagery disappear briefly when I pan or resize?
The old image no longer matches the new viewport. The app invalidates it and loads a matching image instead of painting geographically misplaced weather. Controls can be temporarily disabled during a load. Large or rapid view changes may need time to complete.

## Why is radar limited when I zoom far in or use a very large map?
RainViewer tiles are requested within a bounded tile budget and provider zoom limit of 7. The app also rejects radar canvases larger than 1800 × 1200 to control load and memory use. Reduce the map size or change the zoom and retry if the displayed error identifies these limits.

## Can I change radar colors, smoothing, or snow rendering?
The current integration uses Universal Blue coloring with smoothing and separate snow colors. These are fixed request options, not configurable palette controls in the current interface. Radar availability and coverage are determined by the provider.

## Does turning radar off stop NWS monitoring?
No. Turning it off stops its scheduled refresh and viewport timers. An already-running request can finish, but an obsolete result is ignored. NWS polling, active cards, and alert notifications operate independently.

# Connection details
## What does the map Connection details popup actually report?
It shows observed radar state, attempt and success times, last failure, measured load duration, next refresh, available frames, viewport match, newest frame, sanitized errors, and per-host HTTP activity. It describes requests the app has actually observed rather than assuming every configured service is connected.

## Which radar addresses need to be reachable?
Metadata comes from https://api.rainviewer.com/public/weather-maps.json and tiles normally come from https://tilecache.rainviewer.com using the paths returned by that metadata. NWS alerts use api.weather.gov. A successful metadata request does not guarantee tile downloads will succeed.

## What is the difference between Refresh details and Refresh radar?
Refresh details updates the diagnostic snapshot in the popup without making a new network probe. Refresh radar requests actual radar loading. A host with no observed request is explicitly different from a host with a successful HTTP response.

## What do HTTP 403, 429, and 5xx errors mean?
403 means access was refused and can involve provider, firewall, or proxy policy. 429 indicates rate limiting. 5xx indicates a service-side failure. Record the exact host, response, and time; retry later for transient problems rather than repeatedly forcing refreshes.

## How do I handle TLS, DNS, and timeout errors?
Verify the system clock, normal network connectivity, hostname resolution, and any organization-managed proxy or certificate setup. Do not disable TLS verification as a workaround. Include the exact sanitized error from Connection details when reporting a persistent failure.

# Sound alerts
## How do I play alert.mp3 only for tornadoes and hurricanes?
Select the desired profile, open Alerts → Sound Settings…, use Tornado + hurricane, and save the sound events. The preset includes Tornado Warning, Tornado Watch, Hurricane Warning, and Hurricane Watch. Also ensure that the profile's sound switch is enabled and its category overrides allow sound.

## How do I choose a different custom set of sound events?
In Sound Settings, turn off Allow sound for all monitored event types and check the individual desired types. Save sound events. The event must also be monitored for that profile; the sound allowlist cannot create an alert that the profile does not monitor.

## What is the difference between All event types and an explicit list?
Allowing sound for all monitored types follows your monitored selections, including later additions. An explicit allowlist restricts sound to its saved event names. No event sounds clears that allowlist; it does not stop active cards, desktop notifications, or speech.

## How do I test the sound without waiting for weather?
Open Alerts → Test Notification… and choose Test Alert Sound. It is an intentional manual preview and can bypass the automatic event restrictions. A successful test checks local playback, not the NWS connection or a future alert's geographic eligibility.

## Why does the sound test work but an alert stays silent?
Check that monitoring is running and fresh, the profile is enabled, the alert matches its location and event selection, the overall sound switch is on, category rules allow it, and its event is in the sound allowlist. Quiet startup or an already-successful delivery can also explain silence. Open Why did I get this? and Notifications for the recorded decision.

## What should I check if the sound test fails?
Check speaker output, system mute and volume, audio-device selection, and that alert.mp3 is available with the application. Review the error in the log or delivery information. Sound testing is separate from speech and desktop notification support.

# Spoken alerts
## How do I enable speech and choose what is spoken?
Open Alerts → Speech Settings…, enable Read alerts aloud, choose the event types, and save. Its event allowlist is independent of sound and desktop preferences. Use Test voice for a manual preview and verify your system's speech engine is installed.

## Why does speech ignore dozens of alerts when I first start?
Speech is intentionally limited to new events issued after the current monitoring session starts. Existing alerts still appear in cards and history, but they are not read as a backlog. An alert needs a usable timezone-aware NWS issue timestamp after the cutoff, even if it is a tornado or hurricane event.

## How are many simultaneous alerts aggregated?
After a refresh, eligible alerts are grouped by event type. A spoken report names the type, deduplicated affected locations with pauses, and the latest known effective expiration for that batch. For example, multiple Gale Warnings from the same pull become one grouped report rather than a separate speech item per alert.

## Why does speech not read every location in a large batch?
Spoken area lists are bounded to keep a busy-weather report usable: up to 16 areas and a limited text budget, with remaining areas summarized by a count. Read the alert details for the complete location descriptions and individual expiration times.

## Are cancellations and expirations spoken as new alerts?
No. Cancelled, expired, superseded, and no-longer-active events are excluded from new spoken coverage. If a queued or speaking batch becomes invalid, the owned speech process is stopped and remaining eligible unsent alerts can be regrouped. Part of a still-valid report may repeat after such an interruption.

## What engine processes speech notifications?
Speech runs locally in a worker using Windows PowerShell/.NET System.Speech on Windows, or espeak-ng/espeak on Linux. It does not require a cloud speech API key. Installed system voices and engine availability determine voice behavior. The helper also supports the macOS say command, but the primary supported desktop targets are Windows and Linux.

## How do I stop speech that is already playing?
Pause monitoring or exit the app to stop the active speech process and clear pending speech. Changing the allowlist controls future eligibility; use Pause when you need an immediate stop. A single speech process has a timeout so a stuck engine cannot run indefinitely.

## What happens if too many speech reports arrive at once?
Speech is processed in a bounded queue rather than on the GUI thread. It can hold up to 32 event-type batches with up to 1,000 unique versions per batch. Overflow remains pending for a later eligible refresh. Check Notifications for delivery state instead of assuming every fetched alert has already been spoken.

# Desktop notifications
## How do I enable Windows desktop notifications?
Edit the relevant profile and enable Send desktop notifications, then ensure its desktop category rules allow the event. Tornado and hurricane events can use desktop delivery as well as sound, subject to those rules. Verify Windows permits notifications for the running application and is not suppressing them through Focus Assist or Do Not Disturb.

## Can desktop notifications work on Linux?
Yes, when the desktop provides a session notification service and notify-send is available, commonly through libnotify-bin. Run within a graphical user session with its D-Bus environment. A headless shell or missing notification service can prevent delivery even if other application functions work.

## How do I preview a desktop notification?
Open Alerts → Test Notification… and choose Open Desktop Notification Demo. Use the demo's explicit real desktop preview option when you want an actual OS notification. Such previews are intentional tests, not evidence that a live event matches your saved rules.

## Why did Notifications say Submitted but no popup appeared?
Submitted means the application completed or handed off the local delivery request. It does not prove the OS displayed it or that you saw it. Check operating-system permissions, quiet modes, notification center, session service, and the machine's current desktop session.

## Can sound, speech, and desktop be configured independently?
Yes. Sound has its own event allowlist and profile/category gates. Desktop has its profile/category gates. Speech has its independent enabled setting and exact event allowlist. Turning one off does not automatically disable the others.

# Notification rules
## How do profile and category rules interact?
An event must match an enabled profile's geography and monitored selection first. Sound and desktop each have a profile-level switch and category rules such as warning, watch, or advisory. Sound additionally checks its event allowlist. Speech uses its separate speech configuration. Review each applicable gate when a notification seems unexpected.

## Where do I see why an alert notified me?
Open its details and choose Why did I get this? The explanation includes matching locations, geographic decisions, monitored types, channel preferences, startup behavior, and recorded delivery information. It can distinguish the current settings from the decision recorded for the original version.

## Does changing a preference erase previous delivery results?
No. Delivery history preserves what happened for each version and channel. Changing settings affects subsequent eligibility but does not turn a completed sound into an unheard event or erase old explanations. Read timestamps and version details when comparing current rules with past decisions.

## Can the same alert notify me again after it changes?
A meaningful content version has separate delivery decisions from the previously seen version. This allows important updates to be considered without repeatedly notifying for identical data. Successful channels on an unchanged version remain successful; failed channels can be handled independently.

## Why do some older records lack detailed delivery information?
Legacy ID-only tracking may show an alert was seen without preserving channel-specific outcomes. The app treats these as a quiet baseline rather than claiming unknown sound or desktop delivery succeeded. Newer version records provide more detailed receipts.

# Delivery & retries
## How do I use the Notifications tab?
Browse channel outcomes by event, location, state, and attempt count. Select a row for details or use Failed only to focus on problems. Look at the specific version and channel: a speech failure does not imply that desktop or sound also failed.

## What do Pending, Failed, and Suppressed mean?
Pending means a channel has not completed delivery. Failed records an unsuccessful attempt and its reason. Suppressed means the delivery was intentionally prevented by eligibility or preference rules. Other states can explain paused preferences or a version that is no longer current. Read the selected row's details rather than treating every non-success as a network outage.

## Are failed notifications automatically retried?
Eligible failures can be retried on later successful refreshes, up to three automatic attempts per alert version and channel shared across matching profiles. Successful channels are not replayed while another channel retries. The alert must still be current, allowed, and eligible for the channel.

## How do I manually retry a failed channel?
Select its failed entry and use Retry selected failed channel once. This is one explicit extra attempt, including after the automatic budget is exhausted. It does not reset that budget or replay successful other channels. Live retries require monitoring and fresh, current, eligible data.

## Why can I not retry an old sound or spoken alert?
Expired, cancelled, or otherwise inactive alerts should not sound like new live threats. Such versions are ineligible for live sound and speech retries. Use the manual test tools or isolated Demo Mode to preview devices instead of replaying old weather as a live alert.

# History & search
## What is saved in History?
History contains locally recorded alert changes plus records you explicitly download or import. It is not automatically a complete national archive of all past storms. Different versions and lifecycle changes can create multiple rows for the same NWS alert ID.

## How do I search for tornado events?
Open History, enter tornado in the event-type filter, and apply Search. The event filter accepts partial names, so it can find tornado warnings and watches rather than requiring an exact full label. Clear other restrictions if necessary. A successful search can still return nothing if those records were never stored or downloaded.

## Which filters can I combine?
You can combine text, saved location name, partial event type, lifecycle, delivery result, and From/Through dates. Apply Search to run the filters; Clear filters returns to the broader archive. Restrictive combinations can exclude otherwise relevant records.

## How do date filters work?
Optional dates use YYYY-MM-DD and include the selected local calendar days. Reversed ranges are invalid. Live records use recorded time; downloaded records use NWS issue time and are marked as imported. Older legacy records without a usable time may be excluded by a date filter.

## How do I browse or inspect a long result set?
Use Previous and Next to page through 50 results at a time. Select a record to see its source, time basis, changes, and status. View selected alert opens full details. The visible page is only one portion of the matching archive.

## Why does history still show a cancelled or removed alert?
History preserves what happened, including ending transitions. Removing a card or map area does not delete its records. A historical alert can be inactive now, and a downloaded historical alert never needs to have been active in your application.

## What happens to history when I rename a profile?
Historical records retain their original associated location names. Renaming or removing a profile does not rewrite those old associations. Search using the recorded name when investigating older events.

# Seven-day downloads
## How do I download recent NWS history with one click?
Choose Data → Download Latest 7 Days or the corresponding History control. The batch covers the previous 168 hours ending when the download starts; you do not need to type dates. Check History Download Options first if you want to change its coverage or event selections.

## How do I download all US events instead of one state?
Open Data → History Download Options… and choose All US coverage, with the desired weather event types. The one-click download uses those choices. Without saved choices, the default is the selected profile's first state when available, otherwise All US.

## How does the app handle the 5,000-record limit?
It queues seven daily windows and follows pages of up to 500 records. A dense window reaching the safety threshold is split into smaller time windows and fetched again. Versions at overlapping boundaries are deduplicated before the final import. This avoids treating a single capped response as the complete week.

## Why does a nationwide download take longer or show a rising fetched count?
Broad coverage can require many pages and split-window requests. Progress counts can include records refetched during subdivision, so the fetched total is not necessarily the final unique imported count. The work runs in the background; monitoring can continue.

## Can I cancel a download safely?
Use Cancel download. The current request may need to return before cancellation takes effect. Closing the download dialog or exiting also cancels the operation. The batch is imported atomically: a failed or cancelled batch does not leave a partially imported week.

## Are there other download safeguards?
A batch has request, time, unique-version, and minimum-window limits to prevent runaway fetching: approximately 15 minutes, 1,000 requests, 100,000 unique versions, and a one-minute minimum split window. If it cannot safely complete, it reports failure rather than presenting incomplete results as a complete download.

## Can I download last year's tornadoes this way?
No. This feature uses the NWS recent rolling alert archive, roughly seven days, not a multi-year storm database. The oldest edge can be incomplete as data ages out. An empty response is not proof that no event occurred. Use an appropriate historical data source for older research.

## Will downloading history trigger real notifications or change the map?
No. Downloads add historical records only. They do not populate the current live snapshot, mark live alerts as processed, or deliver real sound, speech, or desktop notifications. A later live alert remains subject to normal processing and rules.

# Imports & exports
## How do I export every result matching my History search?
Apply your History filters, then choose Export Matching History CSV…, File → Export Alert History…, or Ctrl+E. The export includes every matching page, using a consistent archive snapshot, not just the visible 50 rows. The resulting CSV is suitable for spreadsheet analysis.

## Why does my export not match text I just typed in a filter?
Exports use the applied History filters. Run Search after editing the form so the visible results and export share the same query. Clear filters and search again if you want the full archive.

## How do I import an existing NWS alert file?
Choose Data → Import NWS Alert Data… and select a local JSON or GeoJSON NWS FeatureCollection. The file must contain supported weather alerts with valid timezone-aware issue timestamps. Imported records are history only; this is not a way to create live alerts or replay notifications.

## What import limits and validation apply?
Local files are limited to 10 MiB and 5,000 features. Invalid required issue times fail the whole import. Existing alert versions are deduplicated. The background import is atomic and can be cancelled by quitting, rather than leaving a partly validated archive.

## Can I import CSV files, profiles, or radar images?
The NWS import expects NWS GeoJSON/JSON, not CSV, profile settings, or map screenshots. CSV export is for analysis and is not a full application backup. Use a closed-application database backup to preserve profiles, settings, receipts, and history together.

## Why do exports use different source and time fields?
Live records, NWS archive downloads, and local GeoJSON imports have different origins and time bases. These labels help distinguish when the app observed an alert from when NWS issued it. Do not interpret every row as a new storm or a live notification.

# Metrics & analysis
## How do I see a summary of historical and active event types?
Open Data → Metrics. It summarizes each event type's historical alert IDs, recorded changes, downloaded changes, and current active count. Reopen or use Refresh to update the local summary; this does not itself fetch NWS or trigger notifications.

## What is the difference between alert IDs and recorded changes?
Historical alert IDs are distinct NWS message identifiers. Recorded changes include versions and lifecycle transitions, so one ID can have several changes. Neither is necessarily a count of unique physical storms. Downloaded changes are a subset of recorded changes.

## Do History filters affect Metrics?
No. Historical totals cover the full stored archive regardless of the current History page or search filters. Active counts use the last-known monitored snapshot for enabled locations and selected types, deduplicate overlapping profiles, and exclude known expirations.

## Why does active count differ from downloaded history?
Downloaded records are historical and do not enter the live snapshot. The active column depends on current monitored matches and the latest available live information. Read connection health when deciding whether that active count is fresh.

## How can I investigate alert frequency or notification reliability?
Use History filters and CSV export for event, date, and location comparisons. Compare distinct IDs with recorded changes to avoid counting updates as separate storms. Use Notifications and its failure details for channel reliability; a submitted local notification is not proof that a person heard or saw it.

# Demo Mode
## How do I open and close Demo Mode?
Choose Tools → Demo Mode. It opens a reusable popup rather than a main tab. Closing normally hides it, preserving its simulated state for this application session. Reopening does not replace your live views or modify real saved locations.

## Which situations can I simulate?
The demo supports new alerts, updates, extensions, cancellations, expirations, connection failure and recovery, and simulated delivery failure. Some ending scenarios need an active simulated alert first, so run the new-alert scenario before cancelling or expiring it.

## Does a simulation contact NWS or pollute real history?
The demo uses its own temporary model, history, map, and delivery data, labeled SIMULATION. Running a scenario does not add fake weather to the real history or change real preferences. Keep live and simulated windows distinct when interpreting results.

## When does the demo produce real sound or desktop popups?
Only when you explicitly enable its real preview options and run an appropriate scenario. Those options are off by default, and merely checking one does not itself notify. Use them deliberately when testing speakers or OS notification support.

# Appearance & settings
## How do I change the font size and theme?
Open Settings → Appearance. Select 10, 12, or 14 pt from the font dropdown and choose a skin from the theme dropdown. Changes apply immediately and persist across app restarts. Some card and map headings retain dedicated typography for readability.

## Which themes are available and what is the default?
Classic is the default light gray theme for a fresh setup. Navy, Graphite, Forest, and Plum provide darker alternatives. An already saved valid selection is preserved rather than reset to Classic on every launch.

## Why are editable fields black on white?
Typing fields deliberately use black text on a light background for contrast, including when a dark skin is selected. This separates editable content from surrounding panels. The operating system still controls native window chrome and some system dialogs.

## Where are tray and login settings?
Open Settings → General. It contains Close to tray and the Windows launch-at-login option. Close it with the native title-bar X; there is no redundant Close button in that popup. The settings are saved for subsequent sessions.

## Can I change time zones or units?
Settings → Time & Units… explains the current behavior. Alert and spoken times follow the computer's local time, radar uses UTC, and source weather units come from NWS. It is informational rather than a custom per-location time-zone or unit-conversion editor.

## Why is the app icon different on a taskbar or title bar?
The application uses the bundled icon.ico for native windows and the Windows application identity. A running old executable, a stale pinned shortcut, or a desktop environment's own icon rules can affect what is shown. Restart the current build and refresh an outdated shortcut before assuming the new icon was not bundled.

# Tray & startup
## How do I keep monitoring when I close the main window?
Enable Close to tray in Settings → General. The window hides only when a usable tray icon is ready. You can also choose File → Minimize to Tray. Monitoring continues only while the application process remains running and the computer is awake.

## How do I restore the window or fully quit?
Use Open Stormwatch from the tray menu to restore it. File → Exit, Ctrl+Q, or the tray's Quit action fully stops the app, including monitoring and speech. The main title-bar close action follows your Close to tray preference.

## Why does the window stay visible instead of hiding?
The app avoids hiding itself without a working way to reopen it. A missing or unsupported tray backend, particularly on some Linux desktops, can keep the main window visible. Review diagnostics and desktop tray support rather than repeatedly closing the window.

## How do I start automatically when I log into Windows?
Enable the Windows launch-at-login option in Settings → General. It creates a per-user startup entry, without requiring an administrator installation, and launches monitoring with --monitor. Packaged executables and source launches use different appropriate startup commands.

## What happens if I move the application after enabling login startup?
The startup entry points to the current installation path. Disable the option before moving the installation, then launch from the new path and enable it again. Verify startup after the next user login. A stale path can leave Windows unable to find the application.

## Will it monitor after I exit, sign out, or shut down?
No. It is a desktop application, not a background system service. Launch-at-login starts it after your user logs in. Sleep, shutdown, loss of network, and a stopped app interrupt live monitoring; tray mode does not prevent those interruptions.

# Data & backup
## Where does Stormwatch store its local data?
On Windows, look under %LOCALAPPDATA%/Stormwatch. On Linux, use $XDG_STATE_HOME/Stormwatch when configured, otherwise ~/.local/state/Stormwatch. Tools → Open Log Folder opens the actual configured destination. The main database is processed-alerts.sqlite3; logs include storm_monitor.log.

## What does the database contain?
It holds saved preferences, profiles, historical records, processed alert versions, and channel delivery information. These are distinct concepts: seeing a version is not the same as successfully sounding, speaking, or submitting a desktop notification for it. Legacy state may also exist in storm_alert_state.json.

## How do I make a complete backup?
Fully exit the app first, rather than merely minimizing to tray. Copy processed-alerts.sqlite3 and any remaining accompanying -wal and -shm files together as one closed-app set. Keep the copy in a safe backup location. CSV exports do not preserve all settings, profiles, or delivery receipts.

## How do I restore a backup?
Keep the application fully closed, preserve a copy of the current data first, then restore the complete compatible database file set to its data directory. The app has no dedicated restore wizard. Avoid mixing a database with unrelated journal files or editing a live database while monitoring is running.

## How do I inspect storage and retention?
Open Data → Storage & Retention… for the current read-only summary. It does not delete records. Clearing the visible feed does not shrink or reset historical data. Do not delete processed-delivery receipts merely to clean the screen, as that can change duplicate-notification behavior.

## Does the app send my history when I report an issue?
Help → Report an Issue… opens the GitHub issue page; it does not automatically attach or send your local logs or history. Review any material you choose to share, especially private location names, coordinates, and message content. NWS geographic resolution and live provider requests still require normal network communication.

# Troubleshooting
## Why are there no active alerts for my location?
Confirm monitoring is running with a recent successful refresh. Check the profile is enabled, its geography is correct, and the desired events are selected. Review other restrictions such as county plus coordinate combinations. There may simply be no currently active selected NWS weather alert for that location.

## Why are alerts nationwide when I expected local coverage?
Inspect every enabled profile for blank geography or broad state selections. All enabled profiles monitor together, not just the one selected in the sidebar. Disable or narrow an unintended nationwide profile and use Why did I get this? to verify the original match.

## Why are old events still in History after they leave the map?
That is expected. Active cleanup removes expired, cancelled, and superseded current data, while History retains the chronology. Search lifecycle and dates to distinguish historical changes from current hazards. Clearing the feed is also separate from deleting stored history.

## What should I do if the interface feels slow?
Avoid unneeded nationwide profiles and overly broad historical queries when local coverage is sufficient. Check whether a large download or import is running. Use paginated views instead of expecting every historical row on screen. Radar viewport size also affects rendering cost. If slowness persists, capture diagnostics and the workload details for a reproducible report.

## Why is speech unavailable on Linux?
Check that espeak-ng or espeak is installed and callable in the desktop session, and verify the system's audio output. Test voice before investigating alert eligibility. A successful audio-file test does not establish that a text-to-speech engine exists.

## Why do notifications stop when the laptop sleeps?
The application cannot poll NWS or deliver new local notifications while the machine is asleep or offline. Keep the computer awake and connected when monitoring is needed. After waking, inspect freshness and allow a successful refresh before relying on last-known displays.

## How do I collect useful information for a bug report?
Record the operating system, Python version or executable build, steps to reproduce, expected result, and actual result. Include timestamps and sanitized errors from Tools → Diagnostics…, the log folder, or radar Connection details as relevant. Use Help → Report an Issue… to open the project issue form and choose what to share.

## Why do source changes not appear in my Windows executable?
A previously built executable contains its own packaged code and data. Updating a source checkout does not rewrite that executable. Rebuild using main.spec on Windows or obtain a build containing the changes, then restart the correct executable. Check shortcuts and startup paths for older copies.

# Keyboard & menus
## Which keyboard shortcuts are available?
F1 opens Documentation. F5 refreshes NWS while monitoring and idle. Ctrl+F in the main window opens History search. Ctrl+E exports history using applied filters. Ctrl+Q exits. Alt+F4 closes the focused window; closing the main window follows Close to tray settings. In Documentation, Ctrl+F focuses this guide's search and Escape hides the guide.

## How do I search this documentation?
Type words into Search all topics. All words must occur somewhere in an answer's topic, question, or body, regardless of capitalization. Matching topics and counts appear on the left; choose one to read its matching FAQs. Visible search terms are highlighted. Clear restores the complete topic list.

## Can I copy instructions or keep help open while using the app?
Yes. Select text in the read-only answer pane and copy it, or use Copy topic to copy the currently displayed topic and answers. The guide is a separate non-modal window, so monitoring and normal app controls remain available. Closing and reopening Documentation preserves its search and selected topic; F1 returns to Quick start.

## How do I navigate the left-side documentation tabs?
Click a topic, scroll the topic list, or focus it and use the arrow keys. The right-hand pane has its own scrollbar for long answers. Resize the popup to give the answer pane more room. The complete guide is bundled locally and does not need an internet connection.

## Where did older menu commands and the Demo tab go?
Use the sidebar for locations and monitored event selections, and the main tabs to change views. Notification delivery is in Notifications. Demo Mode is now under Tools. Sound and speech configuration and testing are in Alerts. General tray and startup settings are in Settings. These replace redundant older controls.

## What does each top-level menu contain?
File provides exports, tray minimization, and exit. Monitoring controls polling and interval. Alerts configures and tests notification channels and clears the feed. Data contains Metrics, recent downloads, imports, exports, source and storage information. Tools provides Demo Mode, diagnostics, and logs. Settings contains General, Appearance, and Time & Units. Help contains this guide, NWS safety information, shortcuts, issue reporting, and About.

# Platform setup
## What does Windows need to run Stormwatch?
Use the current packaged Windows executable, or run the source in a supported Python environment with Tk and requirements.txt installed. The project targets Python 3.12 and 3.13. Keep bundled assets such as icon.ico, alert.mp3, and the data directory with a source installation; the packaged build includes its required resources.

## What does Linux need for the graphical interface?
Run within a graphical desktop session with Tk support, commonly provided by python3-tk, and the Python requirements installed. A remote terminal without a display cannot show the GUI. X11 or an appropriate XWayland desktop setup must be available for native windows.

## Which Linux packages support optional channels?
libnotify-bin commonly provides notify-send for desktop notifications; a working session notification service is also needed. espeak-ng or espeak provides speech. Tray support can require GTK/AppIndicator and PyGObject matching the running Python version, plus a desktop tray host or extension. Missing optional components should be diagnosed separately from core NWS monitoring.

## Is automatic login startup available on Linux?
The built-in startup preference is Windows-specific and is disabled on Linux. The app does not create a Linux desktop autostart entry through that control. Tray availability also varies by desktop environment; do not assume Windows tray behavior is identical on every Linux session.

## What network services are needed for the full app?
NWS provides live alerts, geographic resolution, and recent historical downloads through api.weather.gov. RainViewer provides optional radar metadata and tile imagery. Offline place lookup, bundled map outlines, saved history searches, Metrics, and Documentation can work without fetching new live weather. Provider outages can affect these services independently.
