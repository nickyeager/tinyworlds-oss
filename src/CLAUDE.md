
<!-- rulemetric:start 4f1d74f9-5166-47f8-bb1b-d9a0ced6a951 -->
## When something fails twice
If the same tool call or command fails twice, stop retrying. Print the exact error, state your current hypothesis, and ask me before continuing. Do not silently switch approaches or work around a failing dependency.
<!-- rulemetric:end 4f1d74f9-5166-47f8-bb1b-d9a0ced6a951 -->


<!-- rulemetric:start 2fa99061-b550-417d-be6c-76f14b9e0136 -->
## Definition of Done
A feature is not complete until: (1) it runs locally without errors, (2) the specific user-facing behavior has been verified end-to-end (browser click-through or curl/SQL check), and (3) I state explicitly what I verified and what I did NOT verify. Never report 'done' based only on code being written.
<!-- rulemetric:end 2fa99061-b550-417d-be6c-76f14b9e0136 -->
