# USyd exam timetable → ICS

Save your personalised timetable HTML from:

<https://exams.sydney.edu.au/timetable/personal.php>

## Quick start

1. In your browser, save the personalised page (File → Save Page As...) — e.g. `The University of Sydney: Examinations.html`.
2. Run the converter:

   ```sh
   python3 exam_html_to_ics.py "The University of Sydney: Examinations.html"
   ```

The script parses the SID from the page title and writes an ICS named `{SID}_exam.ics` in the current directory.

## Options

- `--sid SID` — override the detected SID
- `--output PATH` — write to a specific file path

## Behaviour

- LOCATION is formatted as: `Building Venue, Room, Your Seat` (if present)
- DESCRIPTION purposely omits venue/room/seat/map because they are provided in LOCATION and URL

## Requirements

- Python 3.8+

## License

This project is licensed under the MIT Licence
