# Birthdays, a FiestaBoard plugin

Provide a list of names and dates, and see a message on someone’s birthday. No calendar needed, all details are stored in plugin settings.

## Configure

| Setting | Notes |
|---|---|
| Birthdays | One row per person. Date: `MM-DD`, or `YYYY-MM-DD` for ages. |
| Timezone | Defaults to America/Chicago. |
| Upcoming Window | How far ahead `birthdays.upcoming` looks. Default 7 days. |
| Announce on the Board | Takes over the board on birthdays. Off by default. |

### Page recipes

Today’s birthday message, or who’s birthday is next:

```text
{{= IF(birthdays.is_birthday = "true", birthdays.message, "NEXT: " & birthdays.next_formatted) }}
```

Supports Vestaboard and Vestaboard Note