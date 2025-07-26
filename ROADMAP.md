# YouHoard roadmap

### Things I need before I can use it

- Improve the quality selection options in frontend
    - Also do they work?
    - Does it display a custom quality now?
- Deleting videos in the frontend doesn't work
- What of the subscription logic is implemented? 
    - How does quality decision get handled? 
- Up-front de-duping of videos: youhoard should only ever allow one instance of video. So if the user adds a video that's already there -> notification it exists already
    - A subscription tries to get a vid that exists already -> doesn't
        - But what's the smart way to build this?
            - Thinking the subscription functionality, for either a channel or playlist, should store metadata of all available videos. Then the subscription looks at this storage on run and finds the diff between what's 
- When subscribing to a channel the user needs to be able to specify what kind of content on the channel should be dl'd. videos/shorts/live/podcasts are the categories on the yt site, but not sure if those are all formal objects. 

What's this?:

[frontend] 10:40:04 AM [vite-plugin-svelte] /Users/zachmeador/gits/you_hoard/src/components/AddVideoModal.svelte:58:2 A11y: visible, non-interactive elements with an on:click event must be accompanied by a keyboard event handler. Consider whether an interactive element such as <button type="button"> or <a> might be more appropriate. See https://svelte.dev/docs/accessibility-warnings#a11y-click-events-have-key-events for more details.
[frontend] 10:40:04 AM [vite-plugin-svelte] /Users/zachmeador/gits/you_hoard/src/components/AddVideoModal.svelte:58:2 A11y: <div> with click handler must have an ARIA role
[frontend] 10:40:04 AM [vite-plugin-svelte] /Users/zachmeador/gits/you_hoard/src/components/VideoDetailModal.svelte:53:2 A11y: visible, non-interactive elements with an on:click event must be accompanied by a keyboard event handler. Consider whether an interactive element such as <button type="button"> or <a> might be more appropriate. See https://svelte.dev/docs/accessibility-warnings#a11y-click-events-have-key-events for more details.
[frontend] 10:40:04 AM [vite-plugin-svelte] /Users/zachmeador/gits/you_hoard/src/components/VideoDetailModal.svelte:53:2 A11y: <div> with click handler must have an ARIA role

### Soon(tm)

### Eventually

- MCP tools for managing library
- Ability to supply cookies/auth/whatever to let user get private playlist content. Could you also prevent rate-limiting with this? tube archivist supposedly does this but I've never tried it.