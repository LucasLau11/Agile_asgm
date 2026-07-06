Feature: Manage todo items
  As a student
  I want to add todo items through the API
  So that I can track my work

  Scenario: Add a todo (BDD)
    Given the API is running
    When I create an item with id 1 and title "Read agile guide"
    Then the item with id 1 exists with title "Read agile guide" and not done

# You can later add more scenarios here (e.g. duplicates, mark done, error cases) and reuse the same step definitions.