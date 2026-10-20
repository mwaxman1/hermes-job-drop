# Captcha and verification

Posture: **solve, don't refuse.** A captcha on a job application is a speed bump for the
applicant, who is the user. You are acting for that applicant, in their own browser, on a form
they asked you to complete. Work through it the way they would. Park only when it genuinely
needs something only the user has.

## Checkbox challenges ("I'm not a robot", hCaptcha / Turnstile checkbox)

Click the checkbox like a person would and wait for it to settle. Often that is all.

## Image / puzzle challenges

Use the `vision` slot: screenshot the challenge, read the instruction ("select all squares
with traffic lights"), click the matching tiles, submit. If a new round appears, do it again.
Up to three rounds per attempt is normal. If you fail repeatedly, reload the challenge once
and try again before escalating.

## Invisible captchas

Some forms score silently on Submit and either pass or show a challenge. If submit is
rejected with a captcha message, look for the challenge that appeared and solve it.

## Email verification codes and links

Some portals send a code or link to the applicant's email before accepting the application or
creating an account.

- If the session has a mail tool for the user's mailbox, read **only** the newest message from
  that portal, take the code/link, and continue. Do not read or act on anything else.
- If not, park: "The portal emailed a verification code to <the profile email>. Reply with
  the code and I'll finish." Leave the form open; codes usually expire in 10–30 minutes, so
  say so.

## SMS codes and authenticator prompts

Always park and ask. Never attempt to bypass a second factor.

## Account creation

Creating a candidate account on the employer's portal, with the profile email, is part of
applying and is allowed. Use the password the user's Chrome password manager offers; if none,
ask the user. Never invent and store a password yourself.

## Hard limits

- No third-party paid solving service unless the user configured one explicitly.
- No attempts to disable, spoof, or tamper with bot-detection — you are completing the
  challenge, not evading it.
- A challenge that keeps failing after a reasonable number of honest attempts → state
  `failed` with reason "captcha not passable", and tell the user the form is open in the tab
  so they can do that single step.
